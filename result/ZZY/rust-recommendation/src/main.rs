//! Standalone Rust runtime; Python remains available as an independent fallback.

mod api;
mod import;
mod presentation;
mod scoring;
mod store;
mod validation;

use anyhow::{Context, Result, bail, ensure};
use serde_json::json;
use std::{
    collections::BTreeMap,
    io::{Read, Write},
    net::TcpStream,
    path::PathBuf,
    time::Duration,
};
use tiny_http::{Header, Method, Response, Server, StatusCode};

fn usage() {
    println!(
        "achievement-recommendation-rust import --cache-root EXISTING_PYTHON_CACHE --db OUTPUT.sqlite\nachievement-recommendation-rust serve --db OUTPUT.sqlite [--host 127.0.0.1] [--port 8606]\nachievement-recommendation-rust verify --db OUTPUT.sqlite\nachievement-recommendation-rust health [--port 8606]"
    );
}

fn parse() -> Result<(String, BTreeMap<String, String>)> {
    let mut args = std::env::args().skip(1);
    let command = args.next().unwrap_or_else(|| "help".into());
    let mut options = BTreeMap::new();
    while let Some(key) = args.next() {
        ensure!(
            ["--db", "--cache-root", "--host", "--port"].contains(&key.as_str()),
            "未知参数 {key}"
        );
        let value = args.next().context("参数缺少值")?;
        ensure!(options.insert(key, value).is_none(), "不接受重复参数");
    }
    Ok((command, options))
}

fn health(port: u16) -> Result<()> {
    let mut stream = TcpStream::connect_timeout(
        &format!("127.0.0.1:{port}").parse()?,
        Duration::from_secs(5),
    )?;
    stream.set_read_timeout(Some(Duration::from_secs(15)))?;
    stream.write_all(b"GET /api/meta HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n\r\n")?;
    let mut body = String::new();
    stream.read_to_string(&mut body)?;
    ensure!(
        body.starts_with("HTTP/1.1 200") || body.starts_with("HTTP/1.0 200"),
        "推荐接口未就绪"
    );
    Ok(())
}

/// Serve sequentially: disk access and bounded memory take priority over concurrency.
fn serve(db: PathBuf, host: &str, port: u16) -> Result<()> {
    store::verify(&db)?;
    let conn = store::open(&db)?;
    let server =
        Server::http(format!("{host}:{port}")).map_err(|e| anyhow::anyhow!(e.to_string()))?;
    eprintln!("Rust 推荐已就绪 http://{host}:{port}；只读 SQLite，页缓存 8 MiB，逐请求处理");
    for request in server.incoming_requests() {
        let (status, value) = if request.method() != &Method::Get {
            (404, json!({"error":"没有这个页面或接口"}))
        } else {
            api::route(&conn, request.url())
        };
        let payload = serde_json::to_vec(&value)?;
        let response = Response::from_data(payload)
            .with_status_code(StatusCode(status))
            .with_header(
                Header::from_bytes("Content-Type", "application/json; charset=utf-8").unwrap(),
            )
            .with_header(Header::from_bytes("Cache-Control", "no-store").unwrap())
            .with_header(Header::from_bytes("X-Content-Type-Options", "nosniff").unwrap());
        if let Err(error) = request.respond(response) {
            eprintln!("响应连接已断开：{error}");
        }
    }
    Ok(())
}

fn run() -> Result<()> {
    let (command, args) = parse()?;
    let db = PathBuf::from(
        args.get("--db")
            .map(String::as_str)
            .unwrap_or("runtime/recommendation.sqlite"),
    );
    let port: u16 = args
        .get("--port")
        .map(String::as_str)
        .unwrap_or("8606")
        .parse()
        .context("端口须为有效整数")?;
    match command.as_str() {
        "import" => import::build(
            &PathBuf::from(
                args.get("--cache-root")
                    .context("import 需要 --cache-root")?,
            ),
            &db,
        ),
        "serve" => serve(
            db,
            args.get("--host")
                .map(String::as_str)
                .unwrap_or("127.0.0.1"),
            port,
        ),
        "verify" => {
            store::verify(&db)?;
            println!("数据库摘要与完整性检查通过");
            Ok(())
        }
        "health" => health(port),
        "help" | "--help" | "-h" => {
            usage();
            Ok(())
        }
        _ => bail!("未知命令，请运行 help"),
    }
}

fn main() {
    if let Err(error) = run() {
        eprintln!("失败：{error:#}");
        std::process::exit(1);
    }
}
