//! Persistent SQLite storage. Runtime connections cannot mutate the data file.

use anyhow::{Context, Result, ensure};
use rusqlite::{Connection, OpenFlags};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{fs::File, io::Read, path::Path};

pub const FORMAT_VERSION: i64 = 1;

/// Hash a file with a fixed buffer instead of loading it into RAM.
pub fn digest_file(path: &Path) -> Result<String> {
    let mut input = File::open(path).with_context(|| format!("无法打开 {}", path.display()))?;
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 65536];
    loop {
        let n = input.read(&mut buffer)?;
        if n == 0 {
            break;
        }
        hasher.update(&buffer[..n]);
    }
    Ok(format!("{:x}", hasher.finalize()))
}

/// Apply a small page cache; large temporary sorts use disk and mmap is disabled.
pub fn configure(conn: &Connection) -> Result<()> {
    conn.execute_batch("PRAGMA cache_size=-8192; PRAGMA temp_store=FILE; PRAGMA mmap_size=0; PRAGMA trusted_schema=OFF;")?;
    Ok(())
}

/// Open a fully published database read-only, refusing missing or incomplete input.
pub fn open(path: &Path) -> Result<Connection> {
    ensure!(path.is_file(), "推荐数据库不存在，请先运行 import");
    let conn = Connection::open_with_flags(
        path,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )?;
    configure(&conn)?;
    conn.execute_batch("PRAGMA query_only=ON;")?;
    let version: i64 = conn.query_row("PRAGMA user_version", [], |r| r.get(0))?;
    ensure!(
        version == FORMAT_VERSION,
        "不支持的数据库格式，请使用对应版本程序"
    );
    let complete = metadata(&conn, "complete")?;
    ensure!(complete == Value::Bool(true), "推荐数据库未完整导入");
    Ok(conn)
}

/// Load a small version/count record from the persistent database.
pub fn metadata(conn: &Connection, key: &str) -> Result<Value> {
    let text: String = conn.query_row("SELECT value FROM metadata WHERE key=?1", [key], |row| {
        row.get(0)
    })?;
    Ok(serde_json::from_str(&text)?)
}

/// Verify the externally recorded digest and SQLite integrity before serving.
pub fn verify(path: &Path) -> Result<()> {
    let digest_path = path.with_extension("sqlite.sha256");
    let expected = std::fs::read_to_string(&digest_path).context("缺少数据库摘要文件")?;
    ensure!(
        expected.trim() == digest_file(path)?,
        "推荐数据库摘要不一致，拒绝使用损坏缓存"
    );
    let conn = open(path)?;
    let check: String = conn.query_row("PRAGMA quick_check", [], |r| r.get(0))?;
    ensure!(check == "ok", "推荐数据库完整性检查失败");
    Ok(())
}
