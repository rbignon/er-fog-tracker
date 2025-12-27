// UI Rendering - ImGui overlay implementation

use hudhook::imgui::{Condition, FontConfig, FontGlyphRanges, FontSource, StyleColor, WindowFlags};
use hudhook::{ImguiRenderLoop, RenderContext};
use tracing::{debug, info};

use crate::core::color::parse_hex_color;
use crate::core::map_utils::format_map_id;
use crate::core::status_template::{
    render_template, LineSegment, NamedColor, TemplateColor, TemplateContext, TextSpan,
};

use super::tracker::FogRandoTracker;
use super::websocket::ConnectionStatus;

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

            info!(size = font_size, "Custom font registered with imgui");
        } else {
            info!("Using default imgui font");
        }
    }

    fn render(&mut self, ui: &mut hudhook::imgui::Ui) {
        // Handle keyboard shortcuts
        self.handle_hotkeys();

        // Check for fog traversals each frame (includes WebSocket polling)
        self.check_fog_traversal();

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

        // Max content width for text wrapping
        let max_width = 320.0 * scale;

        ui.window("FogRandoTracker")
            .position([dw - 350.0 * scale, 20.0], Condition::FirstUseEver)
            .flags(window_flags)
            .build(|| {
                // Header: no text wrap (user controls line breaks with $n)
                self.render_header(ui, max_width);
                ui.separator();
                // Enable text wrapping for the rest of the content
                let _wrap = ui.push_text_wrap_pos_with_pos(max_width);
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
            debug!(show_ui = self.show_ui, "UI toggled");
        }
        if self.config.keybindings.toggle_debug.is_just_pressed() {
            self.show_debug = !self.show_debug;
            debug!(show_debug = self.show_debug, "Debug toggled");
        }
        if self.config.keybindings.toggle_exits.is_just_pressed() {
            self.show_exits = !self.show_exits;
            debug!(show_exits = self.show_exits, "Exits toggled");
        }
    }

    /// Build template context from current tracker state
    fn build_template_context(&self) -> TemplateContext {
        let map_id = self.get_current_position().map(|(id, _)| format_map_id(id));

        TemplateContext {
            zone: self.current_zone().map(String::from),
            zone_unknown_text: self.config.overlay.zone_unknown_text.clone(),
            discovered: self.discovery_stats().map(|s| s.discovered).unwrap_or(0),
            total: self.discovery_stats().map(|s| s.total).unwrap_or(0),
            server_enabled: self.is_server_enabled(),
            server_connected: matches!(self.ws_status(), ConnectionStatus::Connected),
            map_id,
            deaths: self.read_deaths(),
            igt_ms: self.read_igt(),
            runes: self.read_great_runes_count(),
            kindling: self.read_kindling_count(),
        }
    }

    /// Render header using the configurable status template
    fn render_header(&self, ui: &hudhook::imgui::Ui, max_width: f32) {
        let ctx = self.build_template_context();
        let rendered = render_template(&self.config.overlay.status_template, &ctx);

        for line in &rendered.lines {
            // Get left and right spans
            let left_spans = line.left_spans().unwrap_or(&[]);
            let right_spans = line.right_spans();

            // Render left part
            self.render_spans(ui, left_spans);

            // Render right part if present
            if let Some(spans) = right_spans {
                // Calculate width for right alignment
                let right_text: String = spans.iter().map(|s| s.text.as_str()).collect();
                let right_width = ui.calc_text_size(&right_text)[0];

                ui.same_line_with_pos(max_width - right_width);
                self.render_spans(ui, spans);
            }
        }
    }

    /// Render a sequence of text spans with their respective colors
    fn render_spans(&self, ui: &hudhook::imgui::Ui, spans: &[TextSpan]) {
        let mut first = true;

        for span in spans {
            if span.text.is_empty() {
                continue;
            }

            if !first {
                ui.same_line_with_spacing(0.0, 0.0);
            }
            first = false;

            let color = self.resolve_template_color(&span.color);
            ui.text_colored(color, &span.text);
        }

        // Handle empty case (need to output something for line to register)
        if first {
            ui.text("");
        }
    }

    /// Resolve a TemplateColor to an RGBA value
    fn resolve_template_color(&self, color: &TemplateColor) -> [f32; 4] {
        match color {
            TemplateColor::Default => parse_hex_color(&self.config.overlay.text_color, 1.0),
            TemplateColor::Status => {
                let (status_color, _) = self.get_status_indicator();
                status_color
            }
            TemplateColor::Discovered => {
                parse_hex_color(&self.config.overlay.discovered_color, 1.0)
            }
            TemplateColor::Undiscovered => {
                parse_hex_color(&self.config.overlay.undiscovered_color, 1.0)
            }
            TemplateColor::Disabled => {
                parse_hex_color(&self.config.overlay.text_disabled_color, 1.0)
            }
            TemplateColor::Named(named) => named.to_rgba(),
            TemplateColor::Hex(hex) => parse_hex_color(hex, 1.0),
        }
    }

    /// Get status indicator color based on connection status
    fn get_status_indicator(&self) -> ([f32; 4], &'static str) {
        match self.ws_status() {
            ConnectionStatus::Connected => ([0.0, 1.0, 0.0, 1.0], "Connected"),
            ConnectionStatus::Reconnecting => ([1.0, 0.65, 0.0, 1.0], "Reconnecting"),
            ConnectionStatus::Connecting => ([1.0, 0.65, 0.0, 1.0], "Connecting"),
            ConnectionStatus::Disconnected => ([1.0, 0.0, 0.0, 1.0], "Disconnected"),
            ConnectionStatus::Error => ([1.0, 0.0, 0.0, 1.0], "Error"),
        }
    }

    /// Render debug section (map_id, server URL, SpEffect info, etc.)
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

        // SpEffect debug info
        ui.separator();
        let debug = self.get_speffect_debug();

        // Pointer chain status
        let chain_ok = debug.player_ins.is_some() && debug.sp_effect_ctrl.is_some();
        let chain_color = if chain_ok {
            [0.0, 1.0, 0.0, 1.0] // Green
        } else {
            [1.0, 0.0, 0.0, 1.0] // Red
        };

        ui.text_disabled("SpEffect Chain:");
        ui.same_line();
        if chain_ok {
            ui.text_colored(chain_color, "OK");
        } else {
            ui.text_colored(chain_color, "BROKEN");
        }

        // Show pointer values for debugging
        ui.text_disabled(format!(
            "  WCM: 0x{:X} → {:?}",
            debug.world_chr_man_base,
            debug.world_chr_man_ptr.map(|p| format!("0x{:X}", p))
        ));
        ui.text_disabled(format!(
            "  PlayerIns (+0x{:X}): {:?}",
            debug.player_ins_offset,
            debug.player_ins.map(|p| format!("0x{:X}", p))
        ));
        ui.text_disabled(format!(
            "  SpEffCtrl (+0x178): {:?}",
            debug.sp_effect_ctrl.map(|p| format!("0x{:X}", p))
        ));
        ui.text_disabled(format!(
            "  FirstNode (+0x8): {:?}",
            debug.first_node.map(|p| format!("0x{:X}", p))
        ));

        // Teleport status
        let tp_color = if debug.has_teleport_effect {
            [0.0, 1.0, 0.0, 1.0] // Green = teleporting
        } else {
            [0.5, 0.5, 0.5, 1.0] // Gray = not teleporting
        };
        ui.text_disabled("Teleport (4280):");
        ui.same_line();
        ui.text_colored(
            tp_color,
            if debug.has_teleport_effect {
                "ACTIVE"
            } else {
                "inactive"
            },
        );

        // Show active SpEffects (first 8)
        if !debug.active_effects.is_empty() {
            let display: Vec<String> = debug
                .active_effects
                .iter()
                .take(8)
                .map(|id| id.to_string())
                .collect();
            let suffix = if debug.active_effects.len() > 8 {
                format!("... +{}", debug.active_effects.len() - 8)
            } else {
                String::new()
            };
            ui.text_disabled(format!("Active: [{}]{}", display.join(", "), suffix));
        } else {
            ui.text_disabled("Active: (none or chain broken)");
        }
    }

    /// Render fog exits section
    fn render_exits_section(&self, ui: &hudhook::imgui::Ui) {
        // Get colors from config
        let discovered_color = parse_hex_color(&self.config.overlay.discovered_color, 1.0);
        let undiscovered_color = parse_hex_color(&self.config.overlay.undiscovered_color, 1.0);

        if self.current_exits().is_empty() {
            ui.text_disabled("No exits available");
            return;
        }

        // Show collapsed indicator when exits are hidden
        if !self.show_exits {
            let exits = self.current_exits();
            let discovered = exits.iter().filter(|e| e.target != "???").count();
            let total = exits.len();
            let hotkey = self.config.keybindings.toggle_exits.name();
            ui.text_disabled(format!(
                "Exits: {}/{} ({} to expand)",
                discovered, total, hotkey
            ));
            return;
        }

        for exit in self.current_exits() {
            let dest_color = if exit.target == "???" {
                undiscovered_color
            } else {
                discovered_color
            };

            // Line 1: target zone (or "???")
            let mut dest_line = format!("→ {}", exit.target);
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
