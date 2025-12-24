// Logging configuration for FogRandoTracker

use std::path::PathBuf;
use std::sync::OnceLock;

use tracing::Level;
use tracing_appender::non_blocking::WorkerGuard;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::EnvFilter;

// Keep the guard alive for the lifetime of the program
static LOG_GUARD: OnceLock<Vec<WorkerGuard>> = OnceLock::new();

/// Initialize logging with optional console and file outputs.
///
/// # Arguments
/// * `enable_console` - If true, logs will be written to stdout
/// * `log_file_path` - If Some, logs will be written to this file
pub fn init_logging(enable_console: bool, log_file_path: Option<PathBuf>) {
    let mut guards = Vec::new();

    // Filter: INFO by default, DEBUG for fog_rando_tracker module
    let filter = EnvFilter::builder()
        .with_default_directive(Level::INFO.into())
        .from_env_lossy()
        .add_directive("fog_rando_tracker=debug".parse().unwrap());

    // Create file layer if path is provided
    let file_layer = log_file_path.and_then(|path| {
        let parent = path.parent()?;
        let file_name = path.file_name()?.to_str()?;

        let file_appender = tracing_appender::rolling::never(parent, file_name);
        let (non_blocking, guard) = tracing_appender::non_blocking(file_appender);
        guards.push(guard);

        Some(
            tracing_subscriber::fmt::layer()
                .with_writer(non_blocking)
                .with_ansi(false)
                .with_target(false),
        )
    });

    // Create console layer if enabled
    let console_layer = if enable_console {
        let (non_blocking, guard) = tracing_appender::non_blocking(std::io::stdout());
        guards.push(guard);

        Some(
            tracing_subscriber::fmt::layer()
                .with_writer(non_blocking)
                .with_ansi(false)
                .with_target(false),
        )
    } else {
        None
    };

    // Build and set the subscriber
    tracing_subscriber::registry()
        .with(filter)
        .with(file_layer)
        .with(console_layer)
        .init();

    // Store guards to keep logging alive
    let _ = LOG_GUARD.set(guards);
}
