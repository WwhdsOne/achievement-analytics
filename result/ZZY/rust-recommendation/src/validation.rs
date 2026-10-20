//! Replay frozen source facts one game at a time; all graph lookups stay on disk.
use anyhow::{Context, Result, ensure};
use rusqlite::Connection;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use unicode_casefold::UnicodeCaseFold;
use unicode_normalization::UnicodeNormalization;

const SPECS: [(&str, &str, &str, &str, &str, &str); 4] = [
    (
        "tags",
        "Tag",
        "tag:steamspy:theme",
        "has_tag",
        "game_tags",
        "tag",
    ),
    (
        "genres",
        "Genre",
        "genre:steam",
        "has_genre",
        "steam_appdetails",
        "valve_genres",
    ),
    (
        "developers",
        "DeveloperName",
        "developer:steam-name",
        "developed_by",
        "steam_appdetails",
        "developers",
    ),
    (
        "publishers",
        "PublisherName",
        "publisher:steam-name",
        "published_by",
        "steam_appdetails",
        "publishers",
    ),
];

fn trim(text: &str) -> &str {
    text.trim_matches(|c: char| c.is_whitespace() || ('\u{001c}'..='\u{001f}').contains(&c))
}

fn canonical(field: &str, raw: &str) -> String {
    if field == "tags" {
        trim(raw).case_fold().collect()
    } else {
        trim(raw).nfc().collect()
    }
}

fn entity_id(field: &str, raw: &str) -> String {
    let spec = SPECS.iter().find(|s| s.0 == field).unwrap();
    format!(
        "{}:{:x}",
        spec.2,
        Sha256::digest(canonical(field, raw).as_bytes())
    )
}

fn number(value: &Value) -> Option<f64> {
    value
        .as_f64()
        .or_else(|| value.as_bool().map(|v| if v { 1.0 } else { 0.0 }))
}

fn truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(v) => *v,
        Value::Number(n) => n.as_f64() != Some(0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

/// Parse the ISO forms accepted by date.fromisoformat for frozen release dates.
pub fn release_year(value: &Value) -> Option<i32> {
    use chrono::{Datelike, NaiveDate};
    let text = value.as_str()?;
    // Python date supports calendar and ISO-week basic/extended forms, years1..9999.
    let date = ["%Y-%m-%d", "%Y%m%d", "%G-W%V-%u", "%GW%V%u"]
        .iter()
        .find_map(|format| NaiveDate::parse_from_str(text, format).ok())
        .or_else(|| {
            if (text.len() == 8
                && text.as_bytes().get(4) == Some(&b'-')
                && text.as_bytes().get(5) == Some(&b'W'))
                || (text.len() == 7 && text.as_bytes().get(4) == Some(&b'W'))
            {
                let full = format!("{text}{}1", if text.len() == 8 { "-" } else { "" });
                ["%G-W%V-%u", "%GW%V%u"]
                    .iter()
                    .find_map(|f| NaiveDate::parse_from_str(&full, f).ok())
            } else {
                None
            }
        })?;
    (1..=9999).contains(&date.year()).then_some(date.year())
}

fn eligible(row: &Value) -> bool {
    let name = [&row["name_zh"], &row["name_en"]]
        .into_iter()
        .find(|v| truthy(v));
    let valid_name = name
        .and_then(Value::as_str)
        .is_some_and(|s| !trim(s).is_empty());
    let percentages: Vec<_> = ["min_percent", "mean_percent", "max_percent"]
        .iter()
        .map(|k| number(&row[k]))
        .collect();
    let valid_percent = percentages
        .iter()
        .all(|p| p.is_some_and(|x| (0.0..=100.0).contains(&x)))
        && percentages[0] <= percentages[1]
        && percentages[1] <= percentages[2];
    let ach_count = row["ach_count"].as_i64().is_some_and(|n| n > 0)
        || row["ach_count"].as_bool() == Some(true);
    let tags = row["tags"].as_array().is_some_and(|items| {
        items.iter().any(|item| {
            item.is_object()
                && item["source"] == "steamspy"
                && item["kind"] == "theme"
                && item["tag"].as_str().is_some_and(|s| !trim(s).is_empty())
        })
    });
    row["appid"].as_i64().is_some_and(|a| a > 0)
        && valid_name
        && release_year(&row["release_date"]).is_some_and(|y| y < 2026)
        && row["mapping_unresolved"] == false
        && ach_count
        && valid_percent
        && tags
}

fn game_entity(row: &Value) -> Value {
    let appid = row["appid"].as_i64().unwrap();
    let names: Vec<_> = ["name_zh", "name_en"]
        .iter()
        .filter_map(|key| row[key].as_str())
        .filter(|s| !trim(s).is_empty())
        .collect();
    let raw_names: BTreeSet<_> = names.iter().copied().collect();
    json!({"id":format!("game:{appid}"),"entity_type":"Game","canonical_key":appid.to_string(),"appid":appid,
        "name_en":row["name_en"],"name_zh":row["name_zh"],"display_name":names.first().map(|s|trim(s).to_owned()).unwrap_or_else(||appid.to_string()),
        "raw_names":raw_names,"release_date":row["release_date"],"recommendation_eligible":eligible(row),
        "source_table":"games","source_fields":["appid","name_en","name_zh"]})
}

/// Check entity identity, candidate rules, and canonical names before persistence.
pub fn entity(conn: &Connection, node: &Value) -> Result<()> {
    if node["entity_type"] == "Game" {
        let appid = node["appid"]
            .as_i64()
            .filter(|a| *a > 0)
            .context("游戏实体编号非法")?;
        ensure!(
            node["id"] == format!("game:{appid}"),
            "游戏实体编号与ID不一致"
        );
        let raw: String =
            conn.query_row("SELECT row_json FROM games WHERE appid=?1", [appid], |r| {
                r.get(0)
            })?;
        let row: Value = serde_json::from_str(&raw)?;
        ensure!(
            node == &game_entity(&row),
            "游戏属性或候选资格无法回查冻结快照：{appid}"
        );
    } else {
        let field = SPECS
            .iter()
            .find(|s| node["entity_type"] == s.1)
            .context("名称实体类型非法")?
            .0;
        let key = node["canonical_key"]
            .as_str()
            .filter(|s| !s.is_empty())
            .context("名称实体缺少规范名")?;
        ensure!(
            node["id"] == entity_id(field, key),
            "名称实体ID与规范名不一致"
        );
        let names = node["raw_names"]
            .as_array()
            .filter(|n| !n.is_empty())
            .context("名称实体原名缺失")?;
        let mut raw_names = BTreeSet::new();
        for raw in names {
            let raw = raw.as_str().context("名称实体原名不是文本")?;
            ensure!(canonical(field, raw) == key, "名称实体原名与规范名不一致");
            raw_names.insert(raw);
        }
        ensure!(
            json!(raw_names) == node["raw_names"],
            "名称实体原名顺序或去重不一致"
        );
        let display = raw_names.iter().map(|s| trim(s)).min().unwrap();
        ensure!(node["display_name"] == display, "名称实体展示名不一致");
        ensure!(
            node.as_object().context("非法名称实体")?.len() == 5,
            "名称实体字段契约不一致"
        );
    }
    Ok(())
}

fn expected_edges(row: &Value, graph: &Value) -> BTreeMap<(String, String), Value> {
    let mut expected = BTreeMap::new();
    let appid = row["appid"].as_i64().unwrap();
    for (field, _typ, _prefix, predicate, table, source_field) in SPECS {
        let Some(values) = row[field].as_array() else {
            continue;
        };
        let mut grouped: BTreeMap<String, Vec<Value>> = BTreeMap::new();
        for (index, item) in values.iter().enumerate() {
            let raw = if field == "tags" {
                if !item.is_object() || item["source"] != "steamspy" || item["kind"] != "theme" {
                    continue;
                }
                item["tag"].as_str()
            } else {
                item.as_str()
            };
            let Some(raw) = raw else { continue };
            if canonical(field, raw).is_empty() {
                continue;
            }
            let tags = field == "tags";
            let mut proof = json!({"appid":appid,"snapshot_field":field,"array_index":index,"raw_value":raw,
                "source_table":table,"source_field":source_field,
                "source_filter":if tags{json!({"source":"steamspy","kind":"theme"})}else{json!({})},
                "source_event_time":null,"warehouse_record_time":row[if tags{"spy_fetched_at"}else{"store_fetched_at"}],
                "warehouse_time_field":if tags{"steamspy_games.fetched_at"}else{"steam_appdetails.fetched_at"},
                "time_semantics":if tags{"associated_game_row_update_not_tag_event"}else{"warehouse_row_insert_or_update"}});
            if tags {
                proof["votes"] = item["votes"].clone();
                proof["raw_item"] = item.clone();
            } else {
                proof["extraction_source"] = json!("appdetails_en");
            }
            grouped
                .entry(entity_id(field, raw))
                .or_default()
                .push(proof);
        }
        for (target, proofs) in grouped {
            let subject = format!("game:{appid}");
            let id = format!(
                "edge:{:x}",
                Sha256::digest(serde_json::to_vec(&json!([subject, predicate, target])).unwrap())
            );
            expected.insert((field.to_owned(),target.clone()),json!({"id":id,"subject":subject,"predicate":predicate,"object":target,
                "relation_kind":"source_fact","evidence":proofs,"snapshot_version":graph["binding"]["snapshot_version"],
                "snapshot_sha256":graph["binding"]["snapshot_sha256"]}));
        }
    }
    expected
}

/// Rebuild every source fact and verify complete edge and alias coverage on disk.
pub fn replay(conn: &Connection, graph: &Value) -> Result<Value> {
    let mut games =
        conn.prepare("SELECT appid,row_json,eligible,year FROM games ORDER BY appid")?;
    let mut rows = games.query([])?;
    let mut facts=conn.prepare("SELECT r.field,r.entity_id,r.json,e.json FROM relations r JOIN entities e ON e.id=r.entity_id WHERE r.game_id=?1 ORDER BY r.field,r.entity_id")?;
    let mut count = 0u64;
    let mut relation_count = 0u64;
    let mut evidence_count = 0u64;
    let mut candidates = 0u64;
    let mut relations_by_type: BTreeMap<String, u64> =
        SPECS.iter().map(|s| (s.3.to_owned(), 0)).collect();
    while let Some(record) = rows.next()? {
        let appid: i64 = record.get(0)?;
        let row: Value = serde_json::from_str(&record.get::<_, String>(1)?)?;
        let flag: bool = record.get(2)?;
        let year: Option<i32> = record.get(3)?;
        ensure!(
            flag == eligible(&row) && year == release_year(&row["release_date"]),
            "游戏候选标记或年份与快照不一致：{appid}"
        );
        let game_raw: String = conn.query_row(
            "SELECT json FROM entities WHERE id=?1",
            [format!("game:{appid}")],
            |r| r.get(0),
        )?;
        ensure!(
            serde_json::from_str::<Value>(&game_raw)? == game_entity(&row),
            "图谱未完整保留游戏属性：{appid}"
        );
        let mut expected = expected_edges(&row, graph);
        let mut actual = facts.query([appid])?;
        while let Some(record) = actual.next()? {
            let field: String = record.get(0)?;
            let target: String = record.get(1)?;
            let edge: Value = serde_json::from_str(&record.get::<_, String>(2)?)?;
            let target_node: Value = serde_json::from_str(&record.get::<_, String>(3)?)?;
            let kind = SPECS
                .iter()
                .find(|s| s.0 == field)
                .context("关系字段非法")?
                .1;
            ensure!(
                target_node["entity_type"] == kind && target_node["id"] == target,
                "关系方向或端点类型错误"
            );
            let proof = expected
                .remove(&(field.clone(), target))
                .context("事实边在源字段中不存在")?;
            ensure!(
                edge == proof,
                "事实边ID、来源、原始位置或完整证据与快照不一致：{appid}/{field}"
            );
            evidence_count += edge["evidence"].as_array().unwrap().len() as u64;
            *relations_by_type
                .get_mut(edge["predicate"].as_str().unwrap())
                .unwrap() += 1;
            relation_count += 1;
        }
        ensure!(expected.is_empty(), "图谱未完整覆盖快照游戏关系：{appid}");
        candidates += u64::from(flag);
        count += 1;
        if count % 10000 == 0 {
            eprintln!("已逐游戏回查 {count} 款来源事实");
        }
    }
    // Relations have now been replayed. Their proof raw values can serve as an
    // indexed disk reference for checking each entity's complete original names.
    let mut nodes = conn.prepare("SELECT json FROM entities ORDER BY id")?;
    let mut records = nodes.query([])?;
    let mut entities_by_type: BTreeMap<String, u64> = std::iter::once(("Game".to_owned(), 0))
        .chain(SPECS.iter().map(|s| (s.1.to_owned(), 0)))
        .collect();
    let mut aliases=conn.prepare("SELECT DISTINCT json_extract(proof.value,'$.raw_value') AS raw_name FROM relations r,json_each(r.json,'$.evidence') proof WHERE r.field=?1 AND r.entity_id=?2 ORDER BY raw_name COLLATE BINARY")?;
    while let Some(record) = records.next()? {
        let node: Value = serde_json::from_str(&record.get::<_, String>(0)?)?;
        let typ = node["entity_type"].as_str().context("实体缺少类型")?;
        *entities_by_type.get_mut(typ).context("未知实体类型")? += 1;
        if typ == "Game" {
            continue;
        }
        let field = SPECS.iter().find(|s| s.1 == typ).unwrap().0;
        let raw_names = aliases
            .query_map([field, node["id"].as_str().unwrap()], |r| {
                r.get::<_, String>(0)
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        ensure!(
            !raw_names.is_empty() && json!(raw_names) == node["raw_names"],
            "名称实体原名集合未完整保留快照"
        );
    }
    ensure!(entities_by_type["Game"] == count, "图谱游戏未完整覆盖快照");
    let statistics = json!({"entities":entities_by_type.values().sum::<u64>(),"entities_by_type":entities_by_type,
        "relations":relation_count,"relations_by_type":relations_by_type,"candidates":candidates,"evidence_items":evidence_count});
    ensure!(
        statistics == graph["statistics"],
        "回放事实统计与图谱清单不一致"
    );
    Ok(
        json!({"source_replayed":true,"games":count,"source_facts":relation_count,"evidence_items":evidence_count,
        "candidate_rules_replayed":true,"canonical_entities_verified":true,"complete_relation_coverage":true}),
    )
}
