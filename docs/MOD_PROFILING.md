# Profiling the Fog Rando Tracker Mod with Tracy

This guide explains how to capture a performance trace of the Rust mod while it
runs inside Elden Ring. Profiling is **opt-in**: the default build ships with
zero profiling code, so normal users are not affected.

## What you get

When profiling is enabled, the mod sends a live trace to the Tracy profiler UI
over TCP port `8086`. You can see:

- Per-frame CPU cost of ImGui rendering (`imgui_render` span), one zone per
  rendered frame.
- Per-frame cost of `FogRandoTracker::update` and its work (`tracker_update`).
- Game memory reads: `read_igt`, `read_deaths`, and the two full key-item
  inventory scans `read_great_runes` and `read_kindling_count`. These two scans
  currently run on every frame from the overlay render path, so they are the
  first thing to look at (see "What to look at first").

## Prerequisites

1. **Tracy profiler.** Download from <https://github.com/wolfpld/tracy/releases>.
   The server version **must match** the protocol version embedded in
   `tracy-client-sys`. Check the version table at
   <https://github.com/nagisa/rust_tracy_client> if you bump the `tracy-client`
   / `tracing-tracy` crate versions in `mod/Cargo.toml`.
2. **Windows MSVC toolchain** for building the mod (same as normal dev).
3. **Elden Ring launched offline** (already required for `hudhook` injection).

## Build the profiling DLL

From the repository root, on Windows:

```bat
cd mod
cargo build --lib --release --features profile-tracy
```

The resulting `target\release\fog_rando_tracker.dll` is **only for profiling**.
Do not distribute it to users: it keeps the Tracy client linked in and opens a
TCP listener.

## Capture a trace

1. Start the Tracy profiler (`tracy-profiler.exe`). Click **Connect** and leave
   the address at `127.0.0.1`.
2. Inject the profiling DLL into Elden Ring the same way you normally inject the
   mod (the launcher or your usual injector). You should see a line in the
   configured log file (`logging.log_file`) that reads
   `Tracy profiling client started`.
3. The Tracy UI should pick up the connection within a second. Frames stream in
   live.
4. Play normally. Spans are grouped by name; hover any zone to see its duration.
   Right-click a zone name in the left panel to plot its history across frames.
5. When done, stop capture in Tracy (**File > Save trace...**) to keep the
   result for later analysis, then eject the mod.

## What to look at first

- **`imgui_render` duration.** At 60 FPS the frame budget is 16.6 ms. Everything
  the mod adds to the frame is inside this zone.
- **`read_great_runes` and `read_kindling_count` frequency and cost.** Each is a
  full key-item inventory scan. Today the overlay render path runs these
  (plus a second `read_great_runes` for the rune icons) **every frame**, while
  the stats network send is throttled separately. If you see three inventory
  scans per frame, that is the redundancy item #5 of the port plan targets:
  caching these per frame should remove most of their cost.
- **`tracker_update` vs `imgui_render` ratio.** If rendering dominates,
  investigate the header/exits drawing and the inventory scans. If update
  dominates, investigate warp detection and WebSocket polling.

## Notes and caveats

- The explicit `profile_span!` zones are always named (they use string literal
  names), so they appear in Tracy regardless of symbols. Symbol-based call-stack
  **sampling** is limited by `strip = "symbols"` in `[profile.release]`; if you
  need full sampled call stacks, temporarily remove that line and rebuild.
- Tracy opens a TCP listener on `0.0.0.0:8086`. Do not run a profiling build on
  a machine exposed to an untrusted network.
- EAC is bypassed by launching the game offline; profiling does not require any
  additional anti-cheat workaround.
- The `profile_span!` macro and `frame_mark()` are defined in
  `mod/src/core/profile.rs`. Add new spans there in the same style.

## Adding a new span

```rust
fn my_hot_function() {
    crate::profile_span!("my_hot_function");
    // ... work ...
}
```

Rebuild with `--features profile-tracy` and reconnect Tracy. The new zone
appears automatically.

## Disabling profiling

Build the mod without the feature (the default). All profiling code is compiled
out; the log will no longer show `Tracy profiling client started`.
