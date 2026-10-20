//! Pure presentation projections; clipping never changes ranking or proof paths.
use crate::api::{bindings, metadata};
use crate::scoring::{FIELDS, fsum};
use anyhow::{Result, ensure};
use rusqlite::Connection;
use serde_json::{Value, json};
use std::collections::BTreeMap;

/// Select a display-only title while retaining source names in the report.
pub fn display_title(conn: &Connection, row: &Value) -> Result<Value> {
    let names = metadata(conn, "display_names")?;
    let id = row["appid"].as_i64().unwrap();
    let localized = names["games"][id.to_string()]
        .as_str()
        .filter(|s| !s.is_empty());
    let chinese = row["name_zh"].as_str().unwrap_or("");
    let english = row["name_en"]
        .as_str()
        .filter(|s| !s.is_empty())
        .or_else(|| row["name"].as_str())
        .unwrap_or("");
    let (primary, source) = if let Some(name) = localized {
        (name.to_owned(), "curated_common_chinese_name")
    } else if chinese
        .chars()
        .any(|c| ('\u{3400}'..='\u{9fff}').contains(&c))
    {
        (chinese.to_owned(), "snapshot_chinese_name")
    } else {
        (
            if !english.is_empty() {
                english.to_owned()
            } else if !chinese.is_empty() {
                chinese.to_owned()
            } else {
                format!("Game {id}")
            },
            "original_name_fallback",
        )
    };
    Ok(json!({"display_name":primary,"display_name_en":english,"display_name_source":source}))
}

fn game_name(conn: &Connection, id: i64) -> Result<Value> {
    let raw: String = conn.query_row(
        "SELECT json FROM entities WHERE id=?1",
        [format!("game:{id}")],
        |r| r.get(0),
    )?;
    Ok(serde_json::from_str::<Value>(&raw)?["display_name"].clone())
}

fn put_node(nodes: &mut Vec<Value>, positions: &mut BTreeMap<String, usize>, node: Value) {
    let id = node["id"].as_str().unwrap().to_owned();
    if let Some(index) = positions.get(&id) {
        nodes[*index] = node;
    } else {
        positions.insert(id, nodes.len());
        nodes.push(node);
    }
}

/// Return all contributions and source edges plus a separately clipped SVG graph.
pub fn explain(conn: &Connection, ranking: Value, path_limit: Option<usize>) -> Result<Value> {
    let mut explanations = Vec::new();
    for result in ranking["results"].as_array().unwrap() {
        let seeds = if let Some(seeds) = result["seed_contributions"].as_array() {
            seeds.clone()
        } else {
            vec![
                json!({"appid":ranking["query_appid"],"weight":1.0,"relations":result["relations"]}),
            ]
        };
        let mut catalog = Vec::new();
        let mut relations = Vec::new();
        for seed in &seeds {
            let seed_id = seed["appid"].as_i64().unwrap();
            let seed_weight = seed["weight"].as_f64().unwrap();
            for (field, _typ, predicate, label, _) in FIELDS {
                let c = &seed["relations"][field];
                let paths = c["paths"].as_array().unwrap();
                ensure!(
                    (fsum(paths.iter().map(|p| p["contribution"].as_f64().unwrap()))
                        - c["weighted_score"].as_f64().unwrap())
                    .abs()
                        <= 1e-12,
                    "路径贡献不能重建关系分数，拒绝展示"
                );
                let note = match c["status"].as_str().unwrap() {
                    "matched" => "有共同关系",
                    "no_shared" => "双方有数据，但没有共同实体",
                    "both_missing" => "双方均缺数据，证据不足",
                    "seed_missing" => "种子缺数据，证据不足",
                    "candidate_missing" => "候选缺数据，证据不足",
                    _ => unreachable!(),
                };
                relations.push(json!({"seed_appid":seed_id,"field":field,"label":label,"weight":c["weight"],
                    "seed_weight":seed_weight,"score":c["weighted_score"].as_f64().unwrap()*seed_weight,
                    "status":c["status"],"status_note":format!("{note}{}",if c["weight"].as_f64()==Some(0.0){"；权重0，不计分"}else{""}),
                    "numerator":c["numerator"],"denominator":c["denominator"],"query_only_entities":c["query_only_entities"],
                    "candidate_only_entities":c["candidate_only_entities"],"path_count":paths.len()}));
                for (index, path) in paths.iter().enumerate() {
                    let entity = &path["entity"];
                    for (side, id) in [
                        ("left_edge", seed_id),
                        ("right_edge", result["appid"].as_i64().unwrap()),
                    ] {
                        let edge = &path[side];
                        ensure!(
                            edge["source_verified"] == true
                                && edge["relation_kind"] == "source_fact"
                                && edge.get("score").is_none()
                                && edge["subject"] == format!("game:{id}")
                                && edge["object"] == entity["id"]
                                && edge["predicate"] == predicate
                                && path["predicate"] == predicate,
                            "路径事实来源/方向未通过验证"
                        );
                    }
                    let raw = path["contribution"].as_f64().unwrap();
                    let contribution = path
                        .get("joint_contribution")
                        .and_then(Value::as_f64)
                        .unwrap_or(raw);
                    ensure!(
                        (contribution - raw * seed_weight).abs() <= 1e-12,
                        "联合路径贡献与种子权重不一致"
                    );
                    catalog.push(json!({"key":format!("{seed_id}:{field}:{}",entity["id"].as_str().unwrap()),"seed_appid":seed_id,
                        "field":field,"path_index":index,"entity_id":entity["id"],"name":entity["display_name"],"predicate":path["predicate"],
                        "contribution":contribution,"raw_contribution":raw,"used_for_score":contribution>0.0,
                        "left_fact_id":path["left_edge"]["id"],"right_fact_id":path["right_edge"]["id"]}));
                }
            }
        }
        catalog.sort_by(|a, b| {
            b["contribution"]
                .as_f64()
                .unwrap()
                .total_cmp(&a["contribution"].as_f64().unwrap())
                .then_with(|| a["key"].as_str().unwrap().cmp(b["key"].as_str().unwrap()))
        });
        ensure!(
            (fsum(catalog.iter().map(|p| p["contribution"].as_f64().unwrap()))
                - result["score"].as_f64().unwrap())
            .abs()
                <= 1e-12,
            "全部路径不能重建总分，拒绝展示"
        );
        let shown = path_limit.unwrap_or(catalog.len()).min(catalog.len());
        let candidate_id = result["appid"].as_i64().unwrap();
        let mut nodes = vec![
            json!({"id":format!("game:{candidate_id}"),"type":"Game","label":game_name(conn,candidate_id)?}),
        ];
        let mut positions = BTreeMap::from([(format!("game:{candidate_id}"), 0)]);
        let mut edges = Vec::new();
        for path in &catalog[..shown] {
            let seed_id = path["seed_appid"].as_i64().unwrap();
            let game_id = format!("game:{seed_id}");
            put_node(
                &mut nodes,
                &mut positions,
                json!({"id":game_id,"type":"Game","label":game_name(conn,seed_id)?}),
            );
            let typ = FIELDS.iter().find(|f| path["field"] == f.0).unwrap().1;
            put_node(
                &mut nodes,
                &mut positions,
                json!({"id":path["entity_id"],"type":typ,"label":path["name"]}),
            );
            for (subject, fact_id) in [
                (game_id, path["left_fact_id"].clone()),
                (
                    format!("game:{candidate_id}"),
                    path["right_fact_id"].clone(),
                ),
            ] {
                edges.push(json!({"source":subject,"target":path["entity_id"],"predicate":path["predicate"],"fact_id":fact_id,
                    "path_key":path["key"],"relation_kind":"source_fact"}));
            }
        }
        explanations.push(json!({"appid":candidate_id,"relations":relations,"path_catalog":catalog,"total_paths":catalog.len(),
            "shown_paths":shown,"shown_contribution":fsum(catalog[..shown].iter().map(|p|p["contribution"].as_f64().unwrap())),
            "hidden_contribution":fsum(catalog[shown..].iter().map(|p|p["contribution"].as_f64().unwrap())),"display_graph":{"nodes":nodes,"edges":edges}}));
    }
    let mut ids: BTreeMap<i64, Value> = BTreeMap::new();
    for seed in ranking["seed_checks"].as_array().unwrap() {
        ids.insert(seed["appid"].as_i64().unwrap(), seed.clone());
    }
    for result in ranking["results"].as_array().unwrap() {
        let id = result["appid"].as_i64().unwrap();
        let raw: String =
            conn.query_row("SELECT row_json FROM games WHERE appid=?1", [id], |r| {
                r.get(0)
            })?;
        ids.insert(id, serde_json::from_str(&raw)?);
    }
    let mut names = serde_json::Map::new();
    for (id, row) in ids {
        names.insert(id.to_string(), display_title(conn, &row)?);
    }
    let versions = bindings(conn)?;
    Ok(
        json!({"ranking":ranking,"explanations":explanations,"path_limit":path_limit,"presentation_only":true,
        "query_games":ranking["seed_checks"],"view_version":versions["view_version"],"view_binding":versions["view_binding"],"display_names":names}),
    )
}
