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

        ui.window("FogRandoTracker")
            .position([dw - 320.0, 20.0], Condition::FirstUseEver)
            .size([300.0, 200.0], Condition::FirstUseEver)
            .flags(WindowFlags::ALWAYS_AUTO_RESIZE)
            .build(|| {
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
        if let Some((map_id, zone_name)) = self.get_current_position() {
            let (ww, xx, yy, dd) = (
                (map_id >> 24) & 0xff,
                (map_id >> 16) & 0xff,
                (map_id >> 8) & 0xff,
                map_id & 0xff,
            );
            ui.text(format!("Map: m{:02}_{:02}_{:02}_{:02}", ww, xx, yy, dd));
            ui.text(format!("Zone: {}", zone_name));
        } else {
            ui.text("Zone not available");
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

        // Show fog traversal count
        ui.text(format!("Fog traversals: {}", self.fog_traversal_count));
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
