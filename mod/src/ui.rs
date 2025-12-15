// UI Rendering - ImGui overlay implementation

use hudhook::imgui::{Condition, FontConfig, FontGlyphRanges, FontSource, StyleColor, WindowFlags};
use hudhook::{ImguiRenderLoop, RenderContext};

use crate::config::parse_hex_color;
use crate::tracker::FogRandoTracker;
use crate::websocket::ConnectionStatus;

// =============================================================================
// HUDHOOK IMPLEMENTATION
// =============================================================================

impl ImguiRenderLoop for FogRandoTracker {
    fn initialize<'a>(
        &'a mut self,
        ctx: &mut hudhook::imgui::Context,
        _render_context: &'a mut dyn RenderContext,
    ) {
        // Load custom font if data was pre-loaded
        if let Some(ref font_data) = self.font_data {
            let font_size = self.config.overlay.font_size;

            // Define glyph ranges: Basic Latin + Latin Extended + common symbols
            // This includes characters like ● (U+25CF) and → (U+2192)
            let glyph_ranges = FontGlyphRanges::from_slice(&[
                0x0020, 0x00FF, // Basic Latin + Latin Supplement
                0x2000, 0x206F, // General Punctuation
                0x2500,
                0x25FF, // Box Drawing + Block Elements + Geometric Shapes (includes ●)
                0x2190, 0x21FF, // Arrows (includes →)
                0,
            ]);

            ctx.fonts().add_font(&[FontSource::TtfData {
                data: font_data,
                size_pixels: font_size,
                config: Some(FontConfig {
                    glyph_ranges,
                    ..FontConfig::default()
                }),
            }]);

            println!("Custom font registered with imgui (size: {}px)", font_size);
        } else {
            println!("Using default imgui font");
        }
    }

    fn render(&mut self, ui: &mut hudhook::imgui::Ui) {
        // Handle keyboard shortcuts
        self.handle_hotkeys();

        // Check for fog traversals each frame
        self.check_fog_traversal();

        // Poll WebSocket for status updates
        self.poll_websocket();

        // NOTE: Hudhook crashes if render() doesn't draw anything.
        // We must always call window().build() even when hidden.

        let [dw, _dh] = ui.io().display_size;

        if !self.show_ui {
            // Draw an invisible/empty window to prevent crash
            ui.window("##hidden")
                .position([-100.0, -100.0], Condition::Always)
                .size([1.0, 1.0], Condition::Always)
                .no_decoration()
                .build(|| {});
            return;
        }

        let s = &self.config.overlay;

        // Scale factor for window positioning (based on font size relative to default 16px)
        let scale = s.font_size / 16.0;

        // Parse colors from config
        let bg_color = parse_hex_color(&s.background_color, s.background_opacity);
        let text_color = parse_hex_color(&s.text_color, 1.0);
        let text_disabled_color = parse_hex_color(&s.text_disabled_color, 1.0);
        let border_color = if s.show_border {
            parse_hex_color(&s.border_color, 1.0)
        } else {
            [0.0, 0.0, 0.0, 0.0]
        };

        // Push style colors (tokens are auto-popped when dropped)
        let _bg_token = ui.push_style_color(StyleColor::WindowBg, bg_color);
        let _text_token = ui.push_style_color(StyleColor::Text, text_color);
        let _text_disabled_token =
            ui.push_style_color(StyleColor::TextDisabled, text_disabled_color);
        let _border_token = ui.push_style_color(StyleColor::Border, border_color);

        // Window flags: remove title bar for cleaner look
        let window_flags =
            WindowFlags::NO_TITLE_BAR | WindowFlags::ALWAYS_AUTO_RESIZE | WindowFlags::NO_SCROLLBAR;

        ui.window("FogRandoTracker")
            .position([dw - 350.0 * scale, 20.0], Condition::FirstUseEver)
            .flags(window_flags)
            .build(|| {
                self.render_header(ui);
                ui.separator();
                if self.show_debug {
                    self.render_debug_section(ui);
                    ui.separator();
                }
                self.render_exits_section(ui);
                self.render_status_message(ui);
            });
    }
}

// =============================================================================
// UI SECTIONS
// =============================================================================

impl FogRandoTracker {
    /// Handle keyboard shortcuts
    fn handle_hotkeys(&mut self) {
        if self.config.keybindings.toggle_ui.is_just_pressed() {
            self.show_ui = !self.show_ui;
            println!("UI toggled: show_ui={}", self.show_ui);
        }
        if self.config.keybindings.toggle_debug.is_just_pressed() {
            self.show_debug = !self.show_debug;
            println!("Debug toggled: show_debug={}", self.show_debug);
        }
    }

    /// Render header: zone name + server status indicator + stats
    fn render_header(&self, ui: &hudhook::imgui::Ui) {
        // Zone name (or placeholder)
        let zone_text = self
            .current_zone
            .as_deref()
            .unwrap_or("(traverse a fog to identify)");

        // Build header line with zone name
        ui.text(zone_text);

        // Same line: server indicator + stats
        ui.same_line();

        // Server status indicator (colored dot)
        if self.is_server_enabled() {
            let (dot_color, _) = self.get_status_indicator();
            ui.text_colored(dot_color, "●");
            ui.same_line();
        }

        // Discovery stats
        if let Some(ref stats) = self.discovery_stats {
            ui.text(format!("{}/{}", stats.discovered, stats.total));
        }
    }

    /// Get status indicator color based on connection status
    fn get_status_indicator(&self) -> ([f32; 4], &'static str) {
        match self.ws_status() {
            ConnectionStatus::Connected => ([0.0, 1.0, 0.0, 1.0], "Connected"),
            ConnectionStatus::Reconnecting => ([1.0, 0.65, 0.0, 1.0], "Reconnecting"),
            ConnectionStatus::Connecting => ([1.0, 0.65, 0.0, 1.0], "Connecting"),
            ConnectionStatus::Authenticating => ([1.0, 0.65, 0.0, 1.0], "Authenticating"),
            ConnectionStatus::Disconnected => ([1.0, 0.0, 0.0, 1.0], "Disconnected"),
            ConnectionStatus::Error => ([1.0, 0.0, 0.0, 1.0], "Error"),
        }
    }

    /// Render debug section (map_id, server URL, etc.)
    fn render_debug_section(&self, ui: &hudhook::imgui::Ui) {
        // Map ID
        if let Some((map_id, _)) = self.get_current_position() {
            let (ww, xx, yy, dd) = (
                (map_id >> 24) & 0xff,
                (map_id >> 16) & 0xff,
                (map_id >> 8) & 0xff,
                map_id & 0xff,
            );
            ui.text_disabled(format!("Map: m{:02}_{:02}_{:02}_{:02}", ww, xx, yy, dd));
        }

        // Server info
        if self.is_server_enabled() {
            let (dot_color, status_text) = self.get_status_indicator();
            ui.text_disabled(format!("Server: {}", &self.config.server.url));
            ui.same_line();
            ui.text_colored(dot_color, format!("({})", status_text));
        }
    }

    /// Render fog exits section
    fn render_exits_section(&self, ui: &hudhook::imgui::Ui) {
        // Get colors from config
        let discovered_color = parse_hex_color(&self.config.overlay.discovered_color, 1.0);
        let undiscovered_color = parse_hex_color(&self.config.overlay.undiscovered_color, 1.0);

        if self.current_exits.is_empty() {
            ui.text_disabled("No exits available");
            return;
        }

        for exit in &self.current_exits {
            let dest_color = if exit.destination == "???" {
                undiscovered_color
            } else {
                discovered_color
            };

            // Line 1: destination zone (or "???")
            let mut dest_line = format!("→ {}", exit.destination);
            if let Some(ref from) = exit.from_zone {
                dest_line.push_str(&format!(" [from {}]", from));
            }
            ui.text_colored(dest_color, &dest_line);

            // Line 2: description (how to get there), indented
            if !exit.description.is_empty() {
                ui.text_disabled(format!("  {}", exit.description));
            }
        }
    }

    /// Render status message if any (temporary notifications)
    fn render_status_message(&self, ui: &hudhook::imgui::Ui) {
        if let Some(status) = self.get_status() {
            ui.separator();
            ui.text_colored([1.0, 1.0, 0.0, 1.0], status);
        }
    }
}
