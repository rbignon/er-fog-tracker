//! Profiling helpers for opt-in Tracy instrumentation.
//!
//! When the `profile-tracy` feature is disabled the symbols here are zero-cost
//! no-ops (the macro expands to an empty block, and `frame_mark()` becomes an
//! empty function the compiler inlines away).
//!
//! When the feature is enabled, `profile_span!` expands to an `info_span!`
//! that is guarded-entered, and `frame_mark()` forwards to Tracy.
//!
//! We use `info_span!` (not `debug_span!`) so the spans pass through the
//! global `EnvFilter` (which defaults to "info") and reach the `TracyLayer`.
//! The `fmt` layer does not render span enter/exit events by default, so
//! this adds no noise to the log file.

/// Enter a profiling span scoped to the surrounding block.
///
/// Usage:
/// ```ignore
/// fn hot_path() {
///     crate::profile_span!("hot_path");
///     // ... work ...
/// }
/// ```
///
/// The guard is bound to a hidden local, so the span stays active until the
/// enclosing block ends. Use this form inside inner loops where you do not
/// want to write an explicit `let _g = ...;` line.
#[cfg(feature = "profile-tracy")]
#[macro_export]
macro_rules! profile_span {
    ($name:expr) => {
        let _profile_span_guard = ::tracing::info_span!($name).entered();
    };
    ($name:expr, $($field:tt)*) => {
        let _profile_span_guard = ::tracing::info_span!($name, $($field)*).entered();
    };
}

#[cfg(not(feature = "profile-tracy"))]
#[macro_export]
macro_rules! profile_span {
    ($name:expr) => {};
    ($name:expr, $($field:tt)*) => {};
}

/// Mark the end of a rendered frame for Tracy's timeline.
///
/// Call this once per DX12 present (i.e. at the end of `ImguiRenderLoop::render`).
#[cfg(all(feature = "profile-tracy", target_os = "windows"))]
#[inline]
pub fn frame_mark() {
    tracy_client::Client::running()
        .expect("tracy client not started")
        .frame_mark();
}

#[cfg(not(all(feature = "profile-tracy", target_os = "windows")))]
#[inline]
pub fn frame_mark() {}

#[cfg(test)]
mod tests {
    // Compile-smoke test: the `profile_span!` macro and `frame_mark()` must
    // expand to valid code in whichever feature mode the test is built under
    // (run `cargo test` for the no-op arm, `cargo test --features profile-tracy`
    // for the Tracy arm). This catches a malformed macro before the
    // Windows-only call sites (which Linux never compiles) ever see it.
    #[test]
    fn macro_and_frame_mark_expand() {
        crate::profile_span!("test_span");
        crate::profile_span!("test_span_with_field", field = 1);
        super::frame_mark();
    }
}
