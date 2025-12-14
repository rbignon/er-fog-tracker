// UI Rendering - ImGui overlay implementation

use hudhook::imgui::{Condition, WindowFlags};
use hudhook::ImguiRenderLoop;

use crate::tracker::FogRandoTracker;

// =============================================================================
// HUDHOOK IMPLEMENTATION
// =============================================================================

impl ImguiRenderLoop for FogRandoTracker {
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

        let font_scale = self.config.overlay.font_scale;

        ui.window("FogRandoTracker")
            .position([dw - 320.0 * font_scale, 20.0], Condition::FirstUseEver)
            .size([300.0 * font_scale, 200.0 * font_scale], Condition::FirstUseEver)
            .flags(WindowFlags::ALWAYS_AUTO_RESIZE)
            .build(|| {
                ui.set_window_font_scale(font_scale);
                self.render_position_section(ui);
                ui.separator();
                self.render_server_section(ui);
                self.render_status_message(ui);
                ui.separator();
                self.render_keybindings_section(ui);
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
    }

    /// Render current position section
    fn render_position_section(&self, ui: &hudhook::imgui::Ui) {
        ui.text("=== Current Zone ===");
        if let Some((map_id, _map_str)) = self.get_current_position() {
            let (ww, xx, yy, dd) = (
                (map_id >> 24) & 0xff,
                (map_id >> 16) & 0xff,
                (map_id >> 8) & 0xff,
                map_id & 0xff,
            );
            ui.text(format!("Map: m{:02}_{:02}_{:02}_{:02}", ww, xx, yy, dd));

            // Show resolved zone name if available (from server after fog traversal)
            if let Some(ref zone) = self.current_zone {
                ui.text(format!("Zone: {}", zone));
            } else {
                ui.text_disabled("Zone: (traverse a fog to identify)");
            }
        } else {
            ui.text("Zone not available");
        }

        // Display fog exits if available
        if !self.current_exits.is_empty() {
            ui.spacing();
            ui.text("=== Fog Exits ===");
            for exit in &self.current_exits {
                let dest_color = if exit.destination == "???" {
                    [0.7, 0.7, 0.7, 1.0] // Gray for undiscovered
                } else {
                    [0.5, 1.0, 0.5, 1.0] // Green for discovered
                };

                // Line 1: destination zone (or "???")
                let mut dest_line = format!("→ {}", exit.destination);
                if let Some(ref from) = exit.from_zone {
                    dest_line.push_str(&format!(" [from {}]", from));
                }
                ui.text_colored(dest_color, &dest_line);

                // Line 2: description (how to get there), indented
                if !exit.description.is_empty() {
                    ui.text_disabled(format!("    {}", exit.description));
                }
            }
        }
    }

    /// Render status message if any
    fn render_status_message(&self, ui: &hudhook::imgui::Ui) {
        if let Some(status) = self.get_status() {
            ui.separator();
            ui.text_colored([1.0, 1.0, 0.0, 1.0], status);
        }
    }

    /// Render server connection status section
    fn render_server_section(&self, ui: &hudhook::imgui::Ui) {
        ui.text("=== Server ===");

        if !self.is_server_enabled() {
            ui.text_disabled("Not configured");
            return;
        }

        let status = self.ws_status();
        let color = status.display_color();
        let text = status.display_text();

        ui.text_colored(color, format!("● {}", text));

        // Show discovery stats from server
        if let Some(ref stats) = self.discovery_stats {
            ui.text(format!(
                "Discovered: {}/{} ({:.0}%)",
                stats.discovered, stats.total, stats.percent
            ));
        } else {
            ui.text_disabled("Discovered: -/-");
        }
    }

    /// Render keybindings help section
    fn render_keybindings_section(&self, ui: &hudhook::imgui::Ui) {
        ui.text("=== Keybindings ===");
        ui.text_disabled(format!(
            "{}: Toggle UI",
            self.config.keybindings.toggle_ui.name()
        ));
    }
}
