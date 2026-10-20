//! Stream candidate profiles from disk and retain only the requested top-k.
use crate::api::{bindings, describe, metadata};
use anyhow::Result;
use rusqlite::Connection;
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet, HashMap};

pub const FIELDS: [(&str, &str, &str, &str, f64); 4] = [
    ("tags", "Tag", "has_tag", "SteamSpy主题标签", 0.75),
    ("genres", "Genre", "has_genre", "Steam官方类型", 0.15),
    (
        "developers",
        "DeveloperName",
        "developed_by",
        "开发商名称",
        0.10,
    ),
    (
        "publishers",
        "PublisherName",
        "published_by",
        "发行商名称",
        0.0,
    ),
];
type Profile = BTreeMap<String, BTreeMap<String, Value>>;

/// Faithfully rounded sum using the same partial-sums strategy as math.fsum.
pub fn fsum(values: impl IntoIterator<Item = f64>) -> f64 {
    let mut partials: Vec<f64> = Vec::new();
    for mut x in values {
        let mut i = 0;
        for j in 0..partials.len() {
            let mut y = partials[j];
            if x.abs() < y.abs() {
                std::mem::swap(&mut x, &mut y);
            }
            let hi = x + y;
            let yr = hi - x;
            let lo = y - yr;
            if lo != 0.0 {
                partials[i] = lo;
                i += 1;
            }
            x = hi;
        }
        partials.truncate(i);
        if x != 0.0 {
            partials.push(x);
        }
    }
    let Some(mut hi) = partials.pop() else {
        return 0.0;
    };
    let mut lo = 0.0;
    while let Some(y) = partials.pop() {
        let x = hi;
        hi = x + y;
        let yr = hi - x;
        lo = y - yr;
        if lo != 0.0 {
            break;
        }
    }
    if let Some(last) = partials.last() {
        if (lo < 0.0 && *last < 0.0) || (lo > 0.0 && *last > 0.0) {
            let y = lo * 2.0;
            let x = hi + y;
            let yr = x - hi;
            if y == yr {
                hi = x;
            }
        }
    }
    hi
}

fn profile(conn: &Connection, appid: i64, proofs: bool) -> Result<Profile> {
    let mut result: Profile = FIELDS
        .iter()
        .map(|f| (f.0.to_owned(), BTreeMap::new()))
        .collect();
    let sql = if proofs {
        "SELECT field,entity_id,json FROM relations WHERE game_id=?1 ORDER BY field,entity_id"
    } else {
        "SELECT field,entity_id,NULL FROM relations WHERE game_id=?1 ORDER BY field,entity_id"
    };
    let mut stmt = conn.prepare_cached(sql)?;
    let mut rows = stmt.query([appid])?;
    while let Some(row) = rows.next()? {
        let field: String = row.get(0)?;
        let id: String = row.get(1)?;
        let edge = if proofs {
            let mut value: Value = serde_json::from_str(&row.get::<_, String>(2)?)?;
            value["source_verified"] = true.into();
            value
        } else {
            Value::Null
        };
        result.get_mut(&field).unwrap().insert(id, edge);
    }
    Ok(result)
}

fn entity(conn: &Connection, id: &str) -> Result<Value> {
    let raw: String =
        conn.query_row("SELECT json FROM entities WHERE id=?1", [id], |r| r.get(0))?;
    Ok(serde_json::from_str(&raw)?)
}

fn name(conn: &Connection, appid: i64) -> Result<Value> {
    Ok(entity(conn, &format!("game:{appid}"))?["display_name"].clone())
}

struct Reference<'a> {
    conn: &'a Connection,
    games: i64,
    filter: String,
    excluded: String,
    cache: HashMap<(String, String), (i64, f64)>,
}
impl Reference<'_> {
    fn weight(&mut self, field: &str, id: &str) -> Result<(i64, f64)> {
        let key = (field.to_owned(), id.to_owned());
        if let Some(v) = self.cache.get(&key) {
            return Ok(*v);
        }
        let sql = format!(
            "SELECT COUNT(*) FROM relations r JOIN games g ON g.appid=r.game_id WHERE r.field=?1 AND r.entity_id=?2 AND {} AND g.appid NOT IN ({})",
            self.filter, self.excluded
        );
        let frequency: i64 = self.conn.query_row(&sql, [field, id], |r| r.get(0))?;
        let idf = ((self.games + 1) as f64 / (frequency + 1) as f64).ln() + 1.0;
        self.cache.insert(key, (frequency, idf));
        Ok((frequency, idf))
    }
    fn describe_entity(&mut self, field: &str, id: &str) -> Result<Value> {
        let (df, idf) = self.weight(field, id)?;
        Ok(
            json!({"id":id,"name":entity(self.conn,id)?["display_name"],"idf":idf,"document_frequency":df}),
        )
    }
}

fn components(
    reference: &mut Reference,
    seed: i64,
    query: &Profile,
    candidate: &Profile,
    complete: bool,
    joint: bool,
    seed_weight: f64,
) -> Result<Value> {
    let mut output = serde_json::Map::new();
    for (field, _typ, predicate, _label, weight) in FIELDS {
        let a = &query[field];
        let b = &candidate[field];
        let union: BTreeSet<&String> = a.keys().chain(b.keys()).collect();
        let shared: Vec<_> = a.keys().filter(|e| b.contains_key(*e)).collect();
        let only_a: Vec<_> = a.keys().filter(|e| !b.contains_key(*e)).collect();
        let only_b: Vec<_> = b.keys().filter(|e| !a.contains_key(*e)).collect();
        let mut shared_weights = Vec::new();
        for id in &shared {
            shared_weights.push(reference.weight(field, id)?.1);
        }
        let mut union_weights = Vec::new();
        for id in &union {
            union_weights.push(reference.weight(field, id)?.1);
        }
        let numerator = fsum(shared_weights);
        let denominator = fsum(union_weights);
        let similarity = if denominator != 0.0 {
            numerator / denominator
        } else {
            0.0
        };
        let status = if a.is_empty() && b.is_empty() {
            "both_missing"
        } else if a.is_empty() {
            "seed_missing"
        } else if b.is_empty() {
            "candidate_missing"
        } else if shared.is_empty() {
            "no_shared"
        } else {
            "matched"
        };
        let mut component = json!({"weight":weight,"status":status,"used_for_score":weight>0.0,
            "seed_entity_count":a.len(),"candidate_entity_count":b.len(),"shared_entity_count":shared.len(),
            "numerator":numerator,"denominator":denominator,"similarity":similarity,"weighted_score":weight*similarity});
        if complete {
            let mut describe_many = |ids: Vec<&String>| -> Result<Vec<Value>> {
                ids.into_iter()
                    .map(|id| reference.describe_entity(field, id))
                    .collect()
            };
            component["union_entity_weights"] =
                json!(describe_many(union.iter().copied().collect())?);
            component["query_only_entities"] = json!(describe_many(only_a)?);
            component["candidate_only_entities"] = json!(describe_many(only_b)?);
            if joint {
                component["joint_contribution"] = json!(weight * similarity * seed_weight);
            }
            let mut paths = Vec::new();
            for id in shared {
                let (df, idf) = reference.weight(field, id)?;
                let raw = weight * idf / denominator;
                let mut path = json!({"kind":if joint{"computed_joint_scored_path"}else{"computed_scored_path"},
                    "predicate":predicate,"entity":entity(reference.conn,id)?,"left_edge":a[id],"right_edge":b[id],
                    "idf":idf,"document_frequency":df,"relation_weight":weight,"used_for_score":weight>0.0,"contribution":raw});
                if joint {
                    path["seed_appid"] = json!(seed);
                    path["seed_weight"] = json!(seed_weight);
                    path["joint_contribution"] = json!(raw * seed_weight);
                }
                paths.push(path);
            }
            component["paths"] = json!(paths);
        }
        output.insert(field.to_owned(), component);
    }
    Ok(Value::Object(output))
}

fn score(components: &Value) -> f64 {
    fsum(
        FIELDS
            .iter()
            .map(|f| components[f.0]["weighted_score"].as_f64().unwrap()),
    )
}

fn preference(conn: &Connection, seeds: &[i64], profiles: &[Profile]) -> Result<Value> {
    let mut relations = serde_json::Map::new();
    let mut tradeoffs = Vec::new();
    for (field, _, _, _, _) in FIELDS {
        let mut counts: BTreeMap<&String, usize> = BTreeMap::new();
        for p in profiles {
            for id in p[field].keys() {
                *counts.entry(id).or_default() += 1;
            }
        }
        let describe = |id: &str| -> Result<Value> {
            Ok(
                json!({"id":id,"name":entity(conn,id)?["display_name"],"seed_appids":seeds.iter().zip(profiles).filter_map(|(s,p)|p[field].contains_key(id).then_some(*s)).collect::<Vec<_>>()}),
            )
        };
        let common_all: Vec<_> = counts
            .iter()
            .filter(|(_, n)| **n == seeds.len())
            .map(|(id, _)| describe(id))
            .collect::<Result<_>>()?;
        let common_some: Vec<_> = counts
            .iter()
            .filter(|(_, n)| **n > 1 && **n < seeds.len())
            .map(|(id, _)| describe(id))
            .collect::<Result<_>>()?;
        let mut unique = serde_json::Map::new();
        for (seed, p) in seeds.iter().zip(profiles) {
            unique.insert(
                seed.to_string(),
                json!(
                    p[field]
                        .keys()
                        .filter(|id| counts[id] == 1)
                        .map(|id| describe(id))
                        .collect::<Result<Vec<_>>>()?
                ),
            );
        }
        relations.insert(field.into(),json!({"common_all":common_all,"common_some":common_some,"unique_by_seed":unique,
            "missing_seed_appids":seeds.iter().zip(profiles).filter_map(|(s,p)|p[field].is_empty().then_some(*s)).collect::<Vec<_>>()}));
        if field == "tags" || field == "genres" {
            for a in 0..seeds.len() {
                for b in a + 1..seeds.len() {
                    let left = &profiles[a][field];
                    let right = &profiles[b][field];
                    if !left.is_empty()
                        && !right.is_empty()
                        && !left.keys().any(|id| right.contains_key(id))
                    {
                        tradeoffs.push(json!({"field":field,"seed_appids":[seeds[a],seeds[b]],"reason":"两种子的该关系集合均非空且无交集；只是潜在取舍，不能证明玩法互斥或用户厌恶。"}));
                    }
                }
            }
        }
    }
    Ok(
        json!({"relations":relations,"potential_tradeoffs":tradeoffs,
        "evidence_note":"共同关系与特有关系均来自种子事实；缺失为证据不足。差异不额外扣分；这不是学习所得的用户画像。"}),
    )
}

// Python's .6g formatting for the short evidence sentence (not numerical output).
fn six_significant(value: f64) -> String {
    if value == 0.0 {
        return "0".to_owned();
    }
    let exponent = value.abs().log10().floor() as i32;
    if !(-4..6).contains(&exponent) {
        let formatted = format!("{value:.5e}");
        let (a, b) = formatted.split_once('e').unwrap();
        let mantissa = a.trim_end_matches('0').trim_end_matches('.');
        let exp: i32 = b.parse().unwrap();
        format!(
            "{mantissa}e{}{abs:02}",
            if exp >= 0 { "+" } else { "-" },
            abs = exp.abs()
        )
    } else {
        let digits = (5 - exponent).max(0) as usize;
        let formatted = format!("{value:.digits$}");
        if formatted.contains('.') {
            formatted
                .trim_end_matches('0')
                .trim_end_matches('.')
                .to_owned()
        } else {
            formatted
        }
    }
}

/// Calculate original IDF-Jaccard scores with an on-disk, year-filtered reference.
pub fn recommend(
    conn: &Connection,
    seeds: &[i64],
    year_min: Option<i64>,
    year_max: Option<i64>,
    top_k: usize,
) -> Result<Value> {
    let counts = metadata(conn, "counts")?;
    let versions = bindings(conn)?;
    let graph = metadata(conn, "graph")?;
    let checks = seeds
        .iter()
        .map(|s| describe(conn, *s))
        .collect::<Result<Vec<_>>>()?;
    let mut filter = "g.eligible=1".to_owned();
    if let Some(y) = year_min {
        filter.push_str(&format!(" AND g.year>={y}"));
    }
    if let Some(y) = year_max {
        filter.push_str(&format!(" AND g.year<={y}"));
    }
    let allowed: i64 = conn.query_row(
        &format!("SELECT COUNT(*) FROM games g WHERE {filter}"),
        [],
        |r| r.get(0),
    )?;
    let excluded = seeds
        .iter()
        .map(i64::to_string)
        .collect::<Vec<_>>()
        .join(",");
    let filters = json!({"year_min":year_min,"year_max":year_max,"inclusive":true});
    let mut report = json!({"query_service_version":versions["query_service_version"],"query_binding":versions["query_binding"],
        "filters":filters,"query_appids":seeds,"seed_checks":checks,"snapshot_games":counts["snapshot_games"],
        "candidate_games":counts["candidate_games"],"filtered_candidate_games":allowed,"top_k":top_k,
        "filter_order":"year_filter_then_idf_then_rank_then_top_k"});
    if checks.iter().any(|c| c["recommendation_eligible"] != true) {
        report.as_object_mut().unwrap().extend(json!({"algorithm_version":null,"binding":null,"status":"seed_ineligible","results":[],"idf_reference_games":null,
            "empty_reason":"所选种子未全部通过推荐资格；请查看seed_checks原因，不对其余种子偷偷继续。"}).as_object().unwrap().clone());
        return Ok(report);
    }
    let reference_games: i64 = conn.query_row(
        &format!("SELECT COUNT(*) FROM games g WHERE {filter} AND g.appid NOT IN ({excluded})"),
        [],
        |r| r.get(0),
    )?;
    let mut reference = Reference {
        conn,
        games: reference_games,
        filter: filter.clone(),
        excluded: excluded.clone(),
        cache: HashMap::new(),
    };
    let profiles = seeds
        .iter()
        .map(|s| profile(conn, *s, true))
        .collect::<Result<Vec<_>>>()?;
    let joint = seeds.len() > 1;
    let seed_weight = 1.0 / seeds.len() as f64;
    let sql = format!(
        "SELECT DISTINCT r.game_id FROM relations s JOIN relations r ON r.field=s.field AND r.entity_id=s.entity_id JOIN games g ON g.appid=r.game_id WHERE s.game_id IN ({excluded}) AND s.field IN ('tags','genres','developers') AND {filter} AND r.game_id NOT IN ({excluded}) ORDER BY r.game_id"
    );
    let mut stmt = conn.prepare(&sql)?;
    let mut candidates = stmt.query([])?;
    let mut best: Vec<(f64, i64)> = Vec::new();
    while let Some(row) = candidates.next()? {
        let id: i64 = row.get(0)?;
        let candidate = profile(conn, id, false)?;
        let mut scores = Vec::new();
        for (seed, query) in seeds.iter().zip(&profiles) {
            scores.push(score(&components(
                &mut reference,
                *seed,
                query,
                &candidate,
                false,
                joint,
                seed_weight,
            )?));
        }
        let total = if joint {
            fsum(scores.into_iter().map(|s| s * seed_weight))
        } else {
            scores[0]
        };
        if total <= 0.0 {
            continue;
        }
        let pos = best.partition_point(|(s, a)| *s > total || (*s == total && *a < id));
        if pos < top_k {
            best.insert(pos, (total, id));
            best.truncate(top_k);
        }
    }
    let mut results = Vec::new();
    for (total, id) in best {
        let candidate = profile(conn, id, true)?;
        let details = describe(conn, id)?;
        let mut item = json!({"appid":id,"name":name(conn,id)?,"score":total,"relation_kind":"algorithm_similarity","facts_unchanged":true,
            "release_date":details["release_date"],"release_year":details["release_year"]});
        let mut contributions = Vec::new();
        for (seed, query) in seeds.iter().zip(&profiles) {
            let relations = components(
                &mut reference,
                *seed,
                query,
                &candidate,
                true,
                joint,
                seed_weight,
            )?;
            let s = score(&relations);
            contributions.push(json!({"appid":seed,"score":s,"weight":seed_weight,"contribution":s*seed_weight,"relations":relations}));
        }
        if joint {
            let supported: Vec<_> = contributions
                .iter()
                .filter(|c| c["score"].as_f64().unwrap() > 0.0)
                .map(|c| c["appid"].as_i64().unwrap())
                .collect();
            let unsupported: Vec<_> = seeds
                .iter()
                .copied()
                .filter(|s| !supported.contains(s))
                .collect();
            let relation_contributions: serde_json::Map<String, Value> = FIELDS
                .iter()
                .map(|f| {
                    (
                        f.0.to_owned(),
                        json!(fsum(contributions.iter().map(|s| {
                            s["relations"][f.0]["joint_contribution"].as_f64().unwrap()
                        }))),
                    )
                })
                .collect();
            item["evidence_note"] = json!(format!(
                "种子{supported:?}提供正贡献；种子{unsupported:?}无正贡献且保留零分份额。等权平均允许部分匹配；共同/特有关系见查询画像。同开发商或发行商不等于玩法相似；权重未经人工效果验证。"
            ));
            item["seed_contributions"] = json!(contributions);
            item["relation_contributions"] = json!(relation_contributions);
            item["supported_seed_appids"] = json!(supported);
            item["unsupported_seed_appids"] = json!(unsupported);
        } else {
            let relations = &contributions[0]["relations"];
            let shared = relations["tags"]["shared_entity_count"].as_u64().unwrap();
            let support = FIELDS
                .iter()
                .filter(|f| relations[f.0]["weighted_score"].as_f64().unwrap() > 0.0)
                .map(|f| {
                    format!(
                        "{}(权重{}，贡献{})",
                        f.3,
                        f.4,
                        six_significant(relations[f.0]["weighted_score"].as_f64().unwrap())
                    )
                })
                .collect::<Vec<_>>()
                .join("、");
            item["shared_tag_count"] = json!(shared);
            item["relations"] = relations.clone();
            item["evidence_note"] = json!(format!(
                "{}本次正贡献：{support}。同开发商或同发行商不等于玩法相似；权重为人为配置，尚未通过人工效果验证。",
                if shared == 0 {
                    "没有共同标签；"
                } else {
                    ""
                }
            ));
        }
        results.push(item);
    }
    let mut binding = versions["query_binding"].clone();
    binding["year_filter"] = filters;
    binding["query_service_version"] = versions["query_service_version"].clone();
    binding["algorithm"] = json!(if joint {
        "rust-sqlite-multi-game-equal-mean-v1"
    } else {
        "rust-sqlite-year-filtered-multi-relation-idf-jaccard-v1"
    });
    if joint {
        binding["aggregation"] = json!("equal_mean_over_all_unique_seeds_including_zero_scores");
        binding["candidate_policy"] =
            json!("union_positive_weight_postings_no_per_seed_top_k_truncation");
        binding["tradeoff_policy"] =
            json!("disjoint_nonempty_tags_or_genres_are_potential_only_no_penalty");
        report["preference_profile"] = preference(conn, seeds, &profiles)?;
    } else {
        report["query_appid"] = json!(seeds[0]);
    }
    use sha2::{Digest, Sha256};
    report["algorithm_version"] = json!(format!(
        "rust-{}-score-v1-{:x}",
        if joint { "multi" } else { "filtered-graph" },
        Sha256::digest(serde_json::to_vec(&binding)?)
    ));
    report["binding"] = binding;
    report["graph_version"] = graph["version"].clone();
    report["scoring_index_games"] = json!(reference_games + seeds.len() as i64);
    report["idf_reference_games"] = json!(reference_games);
    report["empty_reason"] = if results.is_empty() {
        json!(if joint {
            "没有其他有效候选或无共享正权重关系；不生成任意fallback。"
        } else {
            "无共享的正权重关系，或没有其他有效候选；不生成任意fallback。"
        })
    } else {
        Value::Null
    };
    report["status"] = json!(if reference_games == 0 {
        "no_candidates"
    } else if results.is_empty() {
        "no_shared_relation"
    } else {
        "ok"
    });
    if reference_games == 0 {
        report["empty_reason"] = json!("年份范围内没有排除全部种子后的有效候选；不生成fallback。");
    }
    report["results"] = json!(results);
    Ok(report)
}
