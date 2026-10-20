//! Read-only HTTP API for the disk-backed frozen recommendation dataset.
use anyhow::{Result, bail};
use rusqlite::{Connection, OptionalExtension};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use unicode_casefold::UnicodeCaseFold;
use unicode_normalization::UnicodeNormalization;

/// Bump whenever normalization rules or their Unicode data dependencies change.
pub const NORMALIZATION_VERSION: &str =
    "nfkc-full-casefold-python-whitespace-v1;unicode-casefold-0.2.0;unicode-normalization-0.1.26";

/// Match Python's NFKC, full Unicode case folding, and whitespace normalization.
pub fn normalize_search(value: &str) -> String {
    value
        .nfkc()
        .case_fold()
        .collect::<String>()
        .split(|c: char| c.is_whitespace() || ('\u{001c}'..='\u{001f}').contains(&c))
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}

/// Read a small immutable metadata document from SQLite.
pub fn metadata(conn: &Connection, key: &str) -> Result<Value> {
    let raw: String = conn.query_row("SELECT value FROM metadata WHERE key=?1", [key], |r| {
        r.get(0)
    })?;
    Ok(serde_json::from_str(&raw)?)
}

/// Describe a game and retain the original eligibility diagnostics.
pub fn describe(conn: &Connection, appid: i64) -> Result<Value> {
    let (raw, eligible, year): (String, bool, Option<i64>) = conn.query_row(
        "SELECT row_json,eligible,year FROM games WHERE appid=?1",
        [appid],
        |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
    )?;
    let row: Value = serde_json::from_str(&raw)?;
    let mut reasons = Vec::new();
    let mut issue =
        |code: &str, message: &str| reasons.push(json!({"code":code,"message":message}));
    match year {
        None => issue(
            "invalid_release_date",
            "发售日期缺失或无效，不能判断原推荐范围。",
        ),
        Some(y) if y >= 2026 => issue(
            "outside_release_scope",
            "发售日期不在原候选要求的2026年以前。",
        ),
        _ => {}
    }
    let name = row["name_zh"]
        .as_str()
        .filter(|s| !s.is_empty())
        .or_else(|| row["name_en"].as_str())
        .unwrap_or("");
    if name.trim().is_empty() {
        issue("missing_name", "缺少有效游戏名称。");
    }
    if row["mapping_unresolved"] != false {
        issue("unresolved_mapping", "成就身份映射未明确解决。");
    }
    if row["ach_count"].as_i64().unwrap_or(0) <= 0 {
        issue("invalid_achievements", "缺少正数成就数量。");
    }
    let percents: Vec<Option<f64>> = ["min_percent", "mean_percent", "max_percent"]
        .iter()
        .map(|k| row[k].as_f64())
        .collect();
    if !percents
        .iter()
        .all(|p| p.is_some_and(|x| (0.0..=100.0).contains(&x)))
        || (percents.iter().all(Option::is_some)
            && !(percents[0] <= percents[1] && percents[1] <= percents[2]))
    {
        issue(
            "invalid_achievement_summary",
            "成就百分比摘要缺失、越界或顺序异常。",
        );
    }
    // Only SteamSpy theme objects count, exactly as the original tag_set.
    let tags = &row["tags"];
    let has_tags = match tags {
        Value::Array(a) => a.iter().any(|item| {
            item.is_object()
                && item["source"] == "steamspy"
                && item["kind"] == "theme"
                && item["tag"].as_str().is_some_and(|v| !v.trim().is_empty())
        }),
        Value::Object(_) | Value::String(_) => false,
        Value::Null => false,
        Value::Bool(false) => false,
        Value::Number(n) if n.as_f64() == Some(0.0) => false,
        _ => {
            issue(
                "invalid_tags",
                "主题标签字段不是可读取的集合，未通过原推荐数据检查。",
            );
            true
        }
    };
    if !has_tags {
        issue("missing_tags", "缺少有效SteamSpy主题标签。");
    }
    drop(issue);
    if !eligible && reasons.is_empty() {
        reasons.push(
            json!({"code":"candidate_rule_failed","message":"未通过原候选唯一身份或数据检查。"}),
        );
    }
    Ok(
        json!({"appid":appid,"name":if name.trim().is_empty(){format!("appid:{appid}")}else{name.to_owned()},
        "name_en":row["name_en"],"name_zh":row["name_zh"],"release_date":row["release_date"],
        "release_year":year,"recommendation_eligible":eligible,"ineligible_reasons":reasons}),
    )
}

/// Bind Rust implementation versions to source code and the imported frozen graph.
pub fn bindings(conn: &Connection) -> Result<Value> {
    use sha2::{Digest, Sha256};
    let graph = metadata(conn, "graph")?;
    let source = json!({"api.rs":format!("{:x}",Sha256::digest(include_bytes!("api.rs"))),
        "scoring.rs":format!("{:x}",Sha256::digest(include_bytes!("scoring.rs"))),
        "presentation.rs":format!("{:x}",Sha256::digest(include_bytes!("presentation.rs")))});
    let binding = json!({"algorithm":"rust-sqlite-snapshot-search-year-filter-v1",
        "graph_version":graph["version"],"graph_manifest_sha256":metadata(conn,"graph_manifest_sha256")?,
        "snapshot_version":graph["binding"]["snapshot_version"],"snapshot_sha256":graph["binding"]["snapshot_sha256"],
        "weights":{"tags":0.75,"genres":0.15,"developers":0.1,"publishers":0.0},
        "search_scope":"full_frozen_snapshot_name_zh_name_en_local_alias_appid_substring_appid_order",
        "filter_policy":"inclusive_release_year_before_candidate_ranking_seed_year_unrestricted",
        "idf_reference":"year_filtered_eligible_candidates_excluding_all_unique_seeds",
        "ineligible_policy":"explain_and_block_entire_query_no_partial_seed_fallback",
        "missing_policy":"fixed_weights_zero_missing_no_renormalization","tie_break":"score_desc_appid_asc",
        "weight_evidence":"heuristic_initial_not_effect_validated","source_sha256":source,
        "storage":"persistent_sqlite_streamed_candidates_no_full_graph_in_memory"});
    let digest = format!("{:x}", Sha256::digest(serde_json::to_vec(&binding)?));
    let query_version = format!("rust-query-service-v1-{digest}");
    let view_binding = json!({"purpose":"multi_game_year_search_readonly_presentation_v1",
        "query_service_version":query_version,"query_binding":binding,
        "clip_policy":"display_only_full_ranking_and_paths_retained","implementation":"rust_sqlite"});
    let view_version = format!(
        "rust-query-view-v1-{:x}",
        Sha256::digest(serde_json::to_vec(&view_binding)?)
    );
    Ok(
        json!({"query_binding":binding,"query_service_version":query_version,
        "view_binding":view_binding,"view_version":view_version,
        "algorithm_version":format!("rust-graph-score-v1-{digest}")}),
    )
}

fn search(conn: &Connection, q: &str, limit: usize, offset: usize) -> Result<Value> {
    if q.chars().count() > 200 || !(1..=100).contains(&limit) {
        bail!("搜索词须为至多200字符文本，limit为1–100整数，offset为非负整数");
    }
    let normalized = normalize_search(q);
    let mut stmt =
        conn.prepare("SELECT appid,search_fields,aliases_json FROM games ORDER BY appid")?;
    let mut rows = stmt.query([])?;
    let mut matches = 0usize;
    let mut results = Vec::new();
    while let Some(row) = rows.next()? {
        let fields: Vec<String> = serde_json::from_str(&row.get::<_, String>(1)?)?;
        if !fields.iter().any(|f| f.contains(&normalized)) {
            continue;
        }
        if matches >= offset && results.len() < limit {
            let appid = row.get(0)?;
            let mut game = describe(conn, appid)?;
            let aliases: Vec<String> = serde_json::from_str(&row.get::<_, String>(2)?)?;
            game["matched_aliases"] = json!(
                aliases
                    .into_iter()
                    .filter(|s| !normalized.is_empty() && normalize_search(s).contains(&normalized))
                    .collect::<Vec<_>>()
            );
            let titles = crate::presentation::display_title(conn, &game)?;
            game.as_object_mut()
                .unwrap()
                .extend(titles.as_object().unwrap().clone());
            results.push(game);
        }
        matches += 1;
    }
    let counts = metadata(conn, "counts")?;
    let b = bindings(conn)?;
    Ok(
        json!({"query_service_version":b["query_service_version"],"query_binding":b["query_binding"],
        "search_scope":"full_frozen_snapshot","snapshot_games":counts["snapshot_games"],"candidate_games":counts["candidate_games"],
        "query":normalized,"total_matches":matches,"limit":limit,"offset":offset,"results":results,
        "limits":"仅搜索此冻结快照；可查不等于可推荐，不是实时云库全量搜索。"}),
    )
}

fn integer(params: &BTreeMap<String, String>, key: &str, default: &str) -> Result<i64> {
    let text = params.get(key).map(String::as_str).unwrap_or(default);
    if text.is_empty() || text.len() > 10 || !text.bytes().all(|c| c.is_ascii_digit()) {
        bail!("{key}须为有效整数");
    }
    Ok(text.parse()?)
}

fn execute(conn: &Connection, target: &str) -> Result<(u16, Value)> {
    if target.chars().count() > 4096 {
        bail!("请求参数过长");
    }
    let parsed = url::Url::parse(&format!("http://localhost{target}"))?;
    let path = parsed.path();
    if path == "/api/meta" && parsed.query().unwrap_or("").is_empty() {
        let b = bindings(conn)?;
        let counts = metadata(conn, "counts")?;
        let mut provenance = metadata(conn, "provenance")?;
        provenance["snapshot_games"] = counts["snapshot_games"].clone();
        return Ok((
            200,
            json!({"view_version":b["view_version"],"view_binding":b["view_binding"],
            "algorithm_version":b["algorithm_version"],"query_service_version":b["query_service_version"],
            "snapshot_games":counts["snapshot_games"],"candidate_games":counts["candidate_games"],
            "limits":"仅搜索固定快照；1–3种子、年份先筛后评分。相似度不是喜欢概率，权重未经独立人工效果验证。",
            "data_loading":provenance,
            "commentary":{"configured":false,"provider":"DeepSeek","model":"deepseek-flash",
                "trigger":"explicit_click","prompt_version":"grounded-game-commentary-v2-structured"}}),
        ));
    }
    if path != "/api/search" && path != "/api/recommend" {
        return Ok((404, json!({"error":"没有这个页面或接口"})));
    }
    let allowed = if path == "/api/search" {
        vec!["q", "limit", "offset"]
    } else {
        vec!["appids", "year_min", "year_max", "top_k", "path_limit"]
    };
    let mut params = BTreeMap::new();
    let pairs: Vec<_> = parsed.query_pairs().collect();
    if parsed
        .query()
        .is_some_and(|q| !q.is_empty() && q.split('&').count() > 6)
    {
        bail!("Max number of fields exceeded");
    }
    for (k, v) in pairs {
        if !allowed.contains(&k.as_ref()) || params.insert(k.into_owned(), v.into_owned()).is_some()
        {
            bail!("不接受未知或重复参数");
        }
    }
    if path == "/api/search" {
        return Ok((
            200,
            search(
                conn,
                params.get("q").map(String::as_str).unwrap_or(""),
                integer(&params, "limit", "20")? as usize,
                integer(&params, "offset", "0")? as usize,
            )?,
        ));
    }
    let raw = params.get("appids").map(String::as_str).unwrap_or("");
    let parts: Vec<_> = raw.split(',').collect();
    if parts.len() > 10
        || parts
            .iter()
            .any(|s| s.is_empty() || s.len() > 10 || !s.bytes().all(|c| c.is_ascii_digit()))
    {
        bail!("appids须为逗号分隔的1–3个唯一游戏appid");
    }
    let mut seeds: Vec<i64> = parts
        .iter()
        .map(|s| s.parse())
        .collect::<std::result::Result<_, _>>()?;
    seeds.sort_unstable();
    seeds.dedup();
    for seed in &seeds {
        if conn
            .query_row("SELECT appid FROM games WHERE appid=?1", [seed], |r| {
                r.get::<_, i64>(0)
            })
            .optional()?
            .is_none()
        {
            bail!("种子须为当前冻结快照中的整数appid列表");
        }
    }
    if !(1..=3).contains(&seeds.len()) {
        bail!("去重后须有1–3款种子游戏");
    }
    let year = |key: &str| -> Result<Option<i64>> {
        if params.get(key).is_none_or(String::is_empty) {
            Ok(None)
        } else {
            let y = integer(&params, key, "")?;
            if !(1..=9999).contains(&y) {
                bail!("年份须为1–9999整数或None");
            }
            Ok(Some(y))
        }
    };
    let year_min = year("year_min")?;
    let year_max = year("year_max")?;
    if year_min.zip(year_max).is_some_and(|(a, b)| a > b) {
        bail!("起始年份不能晚于结束年份");
    }
    let top_k = integer(&params, "top_k", "5")?;
    if !(1..=100).contains(&top_k) {
        bail!("top-k须为1–100整数");
    }
    let path_limit = if params.get("path_limit").is_some_and(|s| s == "all") {
        None
    } else {
        let n = integer(&params, "path_limit", "8")?;
        if !(1..=200).contains(&n) {
            bail!("显示路径上限须为1–200整数或None");
        }
        Some(n as usize)
    };
    let ranking = crate::scoring::recommend(conn, &seeds, year_min, year_max, top_k as usize)?;
    Ok((
        200,
        crate::presentation::explain(conn, ranking, path_limit)?,
    ))
}

/// Route only metadata, frozen search, and explanations; errors never expose SQL.
pub fn route(conn: &Connection, target: &str) -> (u16, Value) {
    match execute(conn, target) {
        Ok(response) => response,
        Err(error) => {
            if error
                .chain()
                .any(|e| e.is::<rusqlite::Error>() || e.is::<serde_json::Error>())
            {
                eprintln!("recommendation request failed: {error:#}");
                (500, json!({"error":"Service error"}))
            } else {
                (400, json!({"error":error.to_string()}))
            }
        }
    }
}
