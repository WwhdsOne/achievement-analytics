//! One-time streaming conversion of the existing frozen Python cache to SQLite.

use crate::{
    api::{NORMALIZATION_VERSION, normalize_search},
    store, validation,
};
use anyhow::{Context, Result, bail, ensure};
use flate2::read::GzDecoder;
use rusqlite::{Connection, params};
use serde::de::{DeserializeSeed, IgnoredAny, MapAccess, SeqAccess, Visitor};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    fmt,
    fs::{self, File},
    io::{BufRead, BufReader, Read, Write},
    path::{Path, PathBuf},
};

const ALIASES: &[u8] = include_bytes!("../../modeling/recommendation/game_aliases.json");
const DISPLAY_NAMES: &[u8] = include_bytes!("../../modeling/recommendation/display_names_zh.json");

struct HashReader<R> {
    reader: R,
    digest: Sha256,
}
impl<R: Read> Read for HashReader<R> {
    fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
        let n = self.reader.read(buf)?;
        self.digest.update(&buf[..n]);
        Ok(n)
    }
}

struct Games<'a, F: FnMut(Value) -> Result<()>>(&'a mut F);
impl<'de, F: FnMut(Value) -> Result<()>> DeserializeSeed<'de> for Games<'_, F> {
    type Value = u64;
    fn deserialize<D: serde::Deserializer<'de>>(self, deserializer: D) -> Result<u64, D::Error> {
        deserializer.deserialize_seq(self)
    }
}
impl<'de, F: FnMut(Value) -> Result<()>> Visitor<'de> for Games<'_, F> {
    type Value = u64;
    fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
        f.write_str("games array")
    }
    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<u64, A::Error> {
        let mut count = 0;
        while let Some(row) = seq.next_element::<Value>()? {
            (self.0)(row).map_err(serde::de::Error::custom)?;
            count += 1;
        }
        Ok(count)
    }
}

struct Snapshot<'a, F: FnMut(Value) -> Result<()>>(&'a mut F);
impl<'de, F: FnMut(Value) -> Result<()>> DeserializeSeed<'de> for Snapshot<'_, F> {
    type Value = u64;
    fn deserialize<D: serde::Deserializer<'de>>(self, deserializer: D) -> Result<u64, D::Error> {
        deserializer.deserialize_map(self)
    }
}
impl<'de, F: FnMut(Value) -> Result<()>> Visitor<'de> for Snapshot<'_, F> {
    type Value = u64;
    fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
        f.write_str("frozen snapshot object")
    }
    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<u64, A::Error> {
        let mut count = None;
        while let Some(key) = map.next_key::<String>()? {
            if key == "games" {
                if count.is_some() {
                    return Err(serde::de::Error::custom("重复 games"));
                }
                count = Some(map.next_value_seed(Games(self.0))?);
            } else {
                map.next_value::<IgnoredAny>()?;
            }
        }
        count.ok_or_else(|| serde::de::Error::custom("缺少 games"))
    }
}

fn load(path: &Path) -> Result<Value> {
    Ok(serde_json::from_reader(BufReader::new(File::open(path)?))?)
}

fn version_name(value: &Value, prefix: &str) -> Result<String> {
    let name = value.as_str().context("缺少版本名")?;
    ensure!(
        name.starts_with(prefix)
            && name[prefix.len()..].chars().all(|c| c.is_ascii_hexdigit())
            && name.len() > prefix.len(),
        "非法版本名"
    );
    Ok(name.to_string())
}

fn write_meta(conn: &Connection, key: &str, value: &Value) -> Result<()> {
    conn.execute(
        "INSERT INTO metadata(key,value) VALUES(?1,?2)",
        params![key, value.to_string()],
    )?;
    Ok(())
}

fn json_lines<F: FnMut(Value) -> Result<()>>(
    path: &Path,
    expected: &str,
    mut insert: F,
) -> Result<u64> {
    let mut handle = BufReader::new(File::open(path)?);
    let mut line = String::new();
    let mut hash = Sha256::new();
    let mut count = 0;
    loop {
        line.clear();
        if handle.read_line(&mut line)? == 0 {
            break;
        }
        hash.update(line.as_bytes());
        insert(serde_json::from_str(&line)?)?;
        count += 1;
        if count % 100_000 == 0 {
            eprintln!(
                "已导入 {}：{count}",
                path.file_name().unwrap().to_string_lossy()
            );
        }
    }
    ensure!(
        format!("{:x}", hash.finalize()) == expected,
        "{} 摘要不一致",
        path.display()
    );
    Ok(count)
}

struct ImportLock(PathBuf);
impl Drop for ImportLock {
    fn drop(&mut self) {
        let _ = fs::remove_dir(&self.0);
    }
}

/// Import once into an atomic, version-bound database; identical input is reused.
pub fn build(cache: &Path, output: &Path) -> Result<()> {
    let parent = output
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent)?;
    let lock_path = output.with_extension("sqlite.import.lock");
    fs::create_dir(&lock_path).with_context(||format!("无法取得导入锁 {}；若前次进程已退出，请按 IMPORT-RECOVERY.md 核查并清理，不要并发导入同一目标",lock_path.display()))?;
    let _lock = ImportLock(lock_path);
    let pointer = load(&cache.join("latest-startup.json"))?;
    let snapshot_version = version_name(&pointer["snapshot_version"], "recommendation-v1-")?;
    let graph_version = version_name(&pointer["graph_version"], "kg-v1-")?;
    let snapshot_dir = cache.join("snapshots").join(&snapshot_version);
    let graph_dir = cache.join("kg").join(&graph_version);
    let snapshot = load(&snapshot_dir.join("manifest.json"))?;
    let graph = load(&graph_dir.join("manifest.json"))?;
    ensure!(
        snapshot["version"] == snapshot_version && graph["version"] == graph_version,
        "指针与清单版本不一致"
    );
    ensure!(
        graph["binding"]["snapshot_version"] == snapshot_version
            && graph["binding"]["snapshot_sha256"] == snapshot["sha256"],
        "快照与图谱绑定不一致"
    );
    let graph_binding = serde_json::to_vec(&graph["binding"])?;
    ensure!(
        format!("kg-v1-{:x}", Sha256::digest(&graph_binding)) == graph_version,
        "图谱版本摘要不一致"
    );
    ensure!(
        store::digest_file(&graph_dir.join("quality.json"))?
            == graph["files"]["quality.json"]["sha256"]
                .as_str()
                .context("质量清单缺少摘要")?,
        "质量文件摘要不一致"
    );
    let aliases: Value = serde_json::from_slice(ALIASES)?;
    let build_binding = json!({
        "format":store::FORMAT_VERSION,"snapshot":snapshot["sha256"],"graph":graph,
        "aliases_sha256":format!("{:x}",Sha256::digest(ALIASES)),
        "display_names_sha256":format!("{:x}",Sha256::digest(DISPLAY_NAMES)),
        "normalization_version":NORMALIZATION_VERSION,
        "dependency_lock_sha256":format!("{:x}",Sha256::digest(include_bytes!("../Cargo.lock"))),
        "validation_sha256":format!("{:x}",Sha256::digest(include_bytes!("validation.rs"))),
        "importer_sha256":format!("{:x}",Sha256::digest(include_bytes!("import.rs"))),
    });
    if output.exists() {
        store::verify(output)?;
        let conn = store::open(output)?;
        ensure!(
            store::metadata(&conn, "build_binding")? == build_binding,
            "已有数据库绑定不同输入，请使用新输出路径；不会覆盖"
        );
        println!("REUSED {}", output.display());
        return Ok(());
    }
    let digest_output = output.with_extension("sqlite.sha256");
    ensure!(
        !digest_output.exists(),
        "目标数据库不存在但摘要文件已存在；请按 IMPORT-RECOVERY.md 核查不完整发布：{}",
        digest_output.display()
    );
    let stage = output.with_extension(format!("sqlite.{}.staging", std::process::id()));
    ensure!(!stage.exists(), "临时导入文件已存在，请先核查");
    let result = build_stage(
        &snapshot_dir,
        &graph_dir,
        &snapshot,
        &graph,
        &aliases,
        &build_binding,
        &stage,
    );
    if let Err(error) = result {
        let _ = fs::remove_file(&stage);
        let _ = fs::remove_file(format!("{}-journal", stage.display()));
        return Err(error);
    }
    File::open(&stage)?.sync_all()?;
    let digest = store::digest_file(&stage)?;
    let digest_stage = stage.with_extension("sha256");
    let mut digest_file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&digest_stage)?;
    writeln!(digest_file, "{digest}")?;
    digest_file.sync_all()?;
    drop(digest_file);
    // Under the exclusive per-target lock, publish the digest first. The data
    // filename appears only after both complete files exist, and is never replaced.
    fs::hard_link(&digest_stage, &digest_output).context("摘要发布失败；已有文件不会被覆盖")?;
    if let Err(error) = fs::hard_link(&stage, output) {
        let _ = fs::remove_file(&digest_output);
        let _ = fs::remove_file(&digest_stage);
        let _ = fs::remove_file(&stage);
        return Err(error).context("数据库发布失败；已有数据库不会被覆盖");
    }
    // Successful publication is independent of best-effort staging cleanup.
    let _ = fs::remove_file(&stage);
    let _ = fs::remove_file(&digest_stage);
    println!("IMPORTED {} SHA256={digest}", output.display());
    Ok(())
}

fn build_stage(
    snapshot_dir: &Path,
    graph_dir: &Path,
    snapshot: &Value,
    graph: &Value,
    aliases: &Value,
    binding: &Value,
    stage: &Path,
) -> Result<()> {
    let conn = Connection::open(stage)?;
    store::configure(&conn)?;
    conn.execute_batch("PRAGMA foreign_keys=ON; PRAGMA journal_mode=DELETE; PRAGMA synchronous=FULL;
        CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE games(appid INTEGER PRIMARY KEY,eligible INTEGER NOT NULL,year INTEGER,row_json TEXT NOT NULL,search_fields TEXT NOT NULL,aliases_json TEXT NOT NULL);
        CREATE TABLE entities(id TEXT PRIMARY KEY,json TEXT NOT NULL);
        CREATE TABLE relations(game_id INTEGER NOT NULL REFERENCES games(appid),field TEXT NOT NULL,entity_id TEXT NOT NULL REFERENCES entities(id),edge_id TEXT NOT NULL,json TEXT NOT NULL,PRIMARY KEY(game_id,field,entity_id));
        BEGIN IMMEDIATE;")?;
    let games_count;
    {
        let mut statement = conn.prepare("INSERT INTO games VALUES(?1,0,?2,?3,?4,?5)")?;
        let mut insert = |row: Value| -> Result<()> {
            let appid = row["appid"].as_i64().context("游戏缺少 appid")?;
            let year = validation::release_year(&row["release_date"]);
            ensure!(appid > 0, "游戏编号必须为正整数");
            let names = aliases["games"][appid.to_string()]["aliases"]
                .as_array()
                .cloned()
                .unwrap_or_default();
            let mut fields = Vec::new();
            for key in ["name_zh", "name_en"] {
                if let Some(value) = row[key].as_str() {
                    fields.push(normalize_search(value));
                }
            }
            fields.push(appid.to_string());
            for name in &names {
                if let Some(s) = name.as_str() {
                    fields.push(normalize_search(s));
                }
            }
            statement.execute(params![
                appid,
                year,
                row.to_string(),
                serde_json::to_string(&fields)?,
                serde_json::to_string(&names)?
            ])?;
            Ok(())
        };
        let gz = GzDecoder::new(BufReader::new(File::open(
            snapshot_dir.join("games.json.gz"),
        )?));
        let mut input = HashReader {
            reader: gz,
            digest: Sha256::new(),
        };
        let mut de = serde_json::Deserializer::from_reader(&mut input);
        games_count = Snapshot(&mut insert).deserialize(&mut de)?;
        de.end()?;
        drop(de);
        ensure!(
            format!("{:x}", input.digest.finalize())
                == snapshot["sha256"].as_str().context("快照缺少摘要")?,
            "快照原文摘要不一致"
        );
    }
    ensure!(
        Some(games_count) == snapshot["games"].as_u64(),
        "快照游戏数量不一致"
    );
    eprintln!("已流式导入 {games_count} 款游戏");
    let entities_count;
    {
        let mut insert = conn.prepare("INSERT INTO entities VALUES(?1,?2)")?;
        let mut qualify = conn.prepare("UPDATE games SET eligible=?1 WHERE appid=?2")?;
        entities_count = json_lines(
            &graph_dir.join("entities.jsonl"),
            graph["files"]["entities.jsonl"]["sha256"]
                .as_str()
                .context("实体缺少摘要")?,
            |entity| {
                validation::entity(&conn, &entity)?;
                insert.execute(params![
                    entity["id"].as_str().context("实体缺少 id")?,
                    entity.to_string()
                ])?;
                if entity["entity_type"] == "Game" {
                    let changed = qualify.execute(params![
                        entity["recommendation_eligible"]
                            .as_bool()
                            .context("缺少候选资格")?,
                        entity["appid"].as_i64().context("缺少游戏编号")?
                    ])?;
                    ensure!(changed == 1, "图谱游戏不在冻结快照中");
                }
                Ok(())
            },
        )?;
    }
    let relations_count;
    {
        let mut insert = conn.prepare("INSERT INTO relations VALUES(?1,?2,?3,?4,?5)")?;
        relations_count = json_lines(
            &graph_dir.join("relations.jsonl"),
            graph["files"]["relations.jsonl"]["sha256"]
                .as_str()
                .context("关系缺少摘要")?,
            |edge| {
                ensure!(
                    edge["snapshot_sha256"] == snapshot["sha256"]
                        && edge["snapshot_version"] == snapshot["version"],
                    "关系来源与快照不一致"
                );
                let appid: i64 = edge["subject"]
                    .as_str()
                    .and_then(|s| s.strip_prefix("game:"))
                    .context("关系主语非法")?
                    .parse()?;
                let field = match edge["predicate"].as_str() {
                    Some("has_tag") => "tags",
                    Some("has_genre") => "genres",
                    Some("developed_by") => "developers",
                    Some("published_by") => "publishers",
                    _ => bail!("未知关系"),
                };
                insert.execute(params![
                    appid,
                    field,
                    edge["object"].as_str().context("缺少关系对象")?,
                    edge["id"].as_str().context("缺少关系编号")?,
                    edge.to_string()
                ])?;
                Ok(())
            },
        )?;
    }
    let candidates: i64 =
        conn.query_row("SELECT count(*) FROM games WHERE eligible=1", [], |r| {
            r.get(0)
        })?;
    ensure!(
        Some(entities_count) == graph["statistics"]["entities"].as_u64()
            && Some(relations_count) == graph["statistics"]["relations"].as_u64()
            && Some(candidates) == graph["statistics"]["candidates"].as_i64(),
        "图谱计数不一致"
    );
    conn.execute_batch("CREATE INDEX relations_lookup ON relations(field,entity_id,game_id); CREATE INDEX games_candidates ON games(eligible,year,appid);")?;
    let source_validation = validation::replay(&conn, graph)?;
    write_meta(&conn, "snapshot", snapshot)?;
    write_meta(&conn, "graph", graph)?;
    write_meta(
        &conn,
        "graph_manifest_sha256",
        &json!(store::digest_file(&graph_dir.join("manifest.json"))?),
    )?;
    write_meta(&conn, "aliases", aliases)?;
    write_meta(
        &conn,
        "display_names",
        &serde_json::from_slice(DISPLAY_NAMES)?,
    )?;
    write_meta(
        &conn,
        "provenance",
        &json!({"source":"persistent_sqlite","database_access":false,"cache_reused":true,"snapshot_version":snapshot["version"],"graph_version":graph["version"],"runtime":"rust","query_storage":"disk_on_demand"}),
    )?;
    write_meta(
        &conn,
        "counts",
        &json!({"snapshot_games":games_count,"candidate_games":candidates,"entities":entities_count,"relations":relations_count}),
    )?;
    write_meta(&conn, "build_binding", binding)?;
    write_meta(&conn, "source_validation", &source_validation)?;
    write_meta(&conn, "complete", &json!(true))?;
    conn.pragma_update(None, "user_version", store::FORMAT_VERSION)?;
    conn.execute_batch("COMMIT; PRAGMA optimize;")?;
    Ok(())
}
