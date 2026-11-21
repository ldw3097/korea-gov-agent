use std::{env, error::Error, net::SocketAddr};

use axum::{Router, extract::ConnectInfo, http::StatusCode, routing::get};
use tokio::net::TcpListener;

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let bind_address = env::var("APP_BIND_ADDR").unwrap_or_else(|_| "127.0.0.1:3000".into());
    let listener = TcpListener::bind(bind_address).await?;
    eprintln!("Listening on {}", listener.local_addr()?);

    let app = Router::new().route("/health", get(health));
    axum::serve(
        listener,
        app.into_make_service_with_connect_info::<SocketAddr>(),
    )
    .await?;
    Ok(())
}

async fn health(ConnectInfo(peer): ConnectInfo<SocketAddr>) -> StatusCode {
    if peer.ip().is_loopback() {
        StatusCode::OK
    } else {
        StatusCode::NOT_FOUND
    }
}
