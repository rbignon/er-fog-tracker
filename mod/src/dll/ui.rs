// UI Rendering - ImGui overlay implementation

use hudhook::imgui::{
    Condition, FontConfig, FontGlyphRanges, FontSource, Image, StyleColor, WindowFlags,
};
use hudhook::{ImguiRenderLoop, RenderContext};
use tracing::{debug, error, info};

use crate::core::color::parse_hex_color;
use crate::core::map_utils::format_map_id;
use crate::core::status_template::{render_template, ContentSpan, TemplateColor, TemplateContext};

use super::hotkey::begin_hotkey_frame;
use super::icon_atlas::IconAtlas;
use super::tracker::FogRandoTracker;
use super::websocket::ConnectionStatus;

// =============================================================================
// HUDHOOK IMPLEMENTATION
// =============================================================================

impl ImguiRenderLoop for FogRandoTracker {
    fn initialize<'a>(
        &'a mut self,
        ctx: &mut hudhook::imgui::Context,
        render_context: &'a mut dyn RenderContext,
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

        // Load icon atlas (single texture containing all icons)
        match IconAtlas::load(render_context) {
            Ok(atlas) => {
                info!("Loaded icon atlas texture");
                self.icon_atlas = Some(atlas);
            }
            Err(e) => {
                error!(error = %e, "Failed to load icon atlas");
            }
        }
    }

    fn render(&mut self, ui: &mut hudhook::imgui::Ui) {
        // Handle keyboard shortcuts
        self.handle_hotkeys();

        // Per-frame update: warp detection, WebSocket polling, stats sync
        self.update();

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
            .position(
                [dw - max_width - s.position_offset_x, s.position_offset_y],
                Condition::FirstUseEver,
            )
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

                // Calculate font scale and max exits based on max_height
                let (exits_font_scale, max_exits) = self.calculate_exits_layout(ui);

                if exits_font_scale < 1.0 {
                    ui.set_window_font_scale(exits_font_scale);
                }
                self.render_exits_section(ui, max_exits);
                if exits_font_scale < 1.0 {
                    ui.set_window_font_scale(1.0);
                }

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
        // Cache all key states at the start of the frame to avoid
        // multiple hotkeys with the same base key interfering with each other
        begin_hotkey_frame();

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
        if self
            .config
            .keybindings
            .toggle_undiscovered_only
            .is_just_pressed()
        {
            self.show_undiscovered_only = !self.show_undiscovered_only;
            debug!(
                show_undiscovered_only = self.show_undiscovered_only,
                "Undiscovered-only filter toggled"
            );
        }
        if self.config.keybindings.upload_logs.is_just_pressed() {
            debug!("Upload logs hotkey pressed");
            self.trigger_log_upload();
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
            scaling: self.current_zone_scaling().map(String::from),
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

            // Calculate available width for left text (leave gap before right text)
            let left_available = if let Some(spans) = right_spans {
                let right_width = self.calculate_spans_width(ui, spans);
                let gap = ui.calc_text_size(" ")[0]; // Minimum gap between left and right
                max_width - right_width - gap
            } else {
                max_width
            };

            // Truncate left text if it would overlap with right text
            let truncated_left = self.truncate_spans_to_width(ui, left_spans, left_available);

            // Render left part
            self.render_content_spans(ui, &truncated_left);

            // Render right part if present
            if let Some(spans) = right_spans {
                // Calculate width for right alignment
                let right_width = self.calculate_spans_width(ui, spans);

                ui.same_line_with_pos(max_width - right_width);
                self.render_content_spans(ui, spans);
            }
        }
    }

    /// Get effective icon size (from config or fallback to font_size)
    fn icon_size(&self) -> f32 {
        self.config
            .overlay
            .icon_size
            .unwrap_or(self.config.overlay.font_size)
    }

    /// Calculate exits layout: font scale and max exits to show
    ///
    /// Returns (font_scale, max_exits):
    /// - font_scale: 1.0 if no scaling needed, or scaled down to fit (min: exits_min_font_scale)
    /// - max_exits: None if all exits fit, Some(n) if truncation needed
    ///
    /// Logic:
    /// 1. If exits fit at normal size -> (1.0, None)
    /// 2. If exits fit with scaling -> (scale, None)
    /// 3. If exits don't fit even at min scale -> (min_scale, Some(n))
    fn calculate_exits_layout(&self, ui: &hudhook::imgui::Ui) -> (f32, Option<usize>) {
        let max_height = match self.config.overlay.max_height {
            Some(h) => h,
            None => return (1.0, None), // No limit configured
        };

        // Get current cursor position (height used by header + debug + separators)
        let current_y = ui.cursor_pos()[1];

        // Reserve space for status message (1 line + separator if status exists)
        let line_height = ui.text_line_height_with_spacing();
        let status_reserve = if self.get_status().is_some() {
            line_height + 4.0 // separator + 1 line
        } else {
            0.0
        };

        // Calculate remaining height for exits
        let remaining_height = max_height - current_y - status_reserve;
        if remaining_height <= 0.0 {
            return (self.config.overlay.exits_min_font_scale, Some(0));
        }

        // Calculate natural height of exits section
        let exits_height = self.estimate_exits_height(ui);
        if exits_height <= 0.0 {
            return (1.0, None);
        }

        // Case 1: Fits at normal size
        if exits_height <= remaining_height {
            return (1.0, None);
        }

        // Case 2: Calculate scale needed
        let scale_needed = remaining_height / exits_height;
        let min_scale = self.config.overlay.exits_min_font_scale;

        if scale_needed >= min_scale {
            // Fits with scaling, no truncation needed
            return (scale_needed, None);
        }

        // Case 3: Need to truncate at min scale
        // Calculate how many exits fit at min scale
        let scaled_line_height = line_height * min_scale;
        let max_exits = self.calculate_exits_that_fit(remaining_height, scaled_line_height);

        (min_scale, max_exits)
    }

    /// Estimate the natural height of the exits section (at scale 1.0)
    fn estimate_exits_height(&self, ui: &hudhook::imgui::Ui) -> f32 {
        let line_height = ui.text_line_height_with_spacing();

        // If no exits or exits hidden, just 1 line
        if self.current_exits().is_empty() || !self.show_exits {
            return line_height;
        }

        // Filter exits like render_exits_section does
        let exits_to_show: Vec<_> = if self.show_undiscovered_only {
            self.current_exits()
                .iter()
                .filter(|e| e.target == "???")
                .collect()
        } else {
            self.current_exits().iter().collect()
        };

        let mut line_count = 0;

        // Header line for undiscovered-only mode
        if self.show_undiscovered_only {
            line_count += 1;
        }

        // Count lines for each exit
        for exit in &exits_to_show {
            line_count += 1; // Target zone line
            if !exit.description.is_empty() {
                line_count += 1; // Description line
            }
        }

        line_count as f32 * line_height
    }

    /// Calculate how many exits fit in the given height at the given line height
    fn calculate_exits_that_fit(&self, available_height: f32, line_height: f32) -> Option<usize> {
        // Get the filtered exits list (sorted same as render_exits_section)
        let mut exits_to_show: Vec<_> = if self.show_undiscovered_only {
            self.current_exits()
                .iter()
                .filter(|e| e.target == "???")
                .collect()
        } else {
            self.current_exits().iter().collect()
        };
        exits_to_show.sort_by_key(|e| e.target != "???");

        if exits_to_show.is_empty() {
            return None;
        }

        // Calculate how many lines we can show
        let mut available_lines = (available_height / line_height) as usize;

        // Reserve 1 line for undiscovered-only header if active
        if self.show_undiscovered_only && available_lines > 0 {
            available_lines -= 1;
        }

        // Count how many exits fit
        let mut exits_that_fit = 0;
        let mut lines_used = 0;

        for exit in &exits_to_show {
            let lines_for_exit = if exit.description.is_empty() { 1 } else { 2 };

            // Reserve 1 line for "+ X others" if we might need to truncate
            let reserve_for_truncation = if exits_that_fit < exits_to_show.len() - 1 {
                1
            } else {
                0
            };

            if lines_used + lines_for_exit + reserve_for_truncation <= available_lines {
                lines_used += lines_for_exit;
                exits_that_fit += 1;
            } else {
                break;
            }
        }

        // If all exits fit, no truncation needed
        if exits_that_fit >= exits_to_show.len() {
            None
        } else {
            Some(exits_that_fit)
        }
    }

    /// Calculate the total width of content spans (text + icons)
    fn calculate_spans_width(&self, ui: &hudhook::imgui::Ui, spans: &[ContentSpan]) -> f32 {
        let icon_size = self.icon_size();
        let icon_spacing = 2.0;

        spans
            .iter()
            .map(|span| match span {
                ContentSpan::Text(text_span) => ui.calc_text_size(&text_span.text)[0],
                ContentSpan::RuneIcons => {
                    // 7 icons + 6 spaces between them
                    7.0 * icon_size + 6.0 * icon_spacing
                }
                ContentSpan::KindlingIcon => icon_size,
                ContentSpan::DeathIcon => icon_size,
            })
            .sum()
    }

    /// Truncate content spans to fit within a maximum width, adding ellipsis if needed
    fn truncate_spans_to_width(
        &self,
        ui: &hudhook::imgui::Ui,
        spans: &[ContentSpan],
        max_width: f32,
    ) -> Vec<ContentSpan> {
        let current_width = self.calculate_spans_width(ui, spans);

        // If it fits, return as-is
        if current_width <= max_width {
            return spans.to_vec();
        }

        let ellipsis = "…";
        let ellipsis_width = ui.calc_text_size(ellipsis)[0];

        // If even ellipsis doesn't fit, return empty
        if max_width < ellipsis_width {
            return vec![];
        }

        let target_width = max_width - ellipsis_width;
        let mut result: Vec<ContentSpan> = Vec::new();
        let mut accumulated_width = 0.0;

        for span in spans {
            match span {
                ContentSpan::Text(text_span) => {
                    let span_width = ui.calc_text_size(&text_span.text)[0];

                    if accumulated_width + span_width <= target_width {
                        // Span fits entirely
                        result.push(span.clone());
                        accumulated_width += span_width;
                    } else {
                        // Need to truncate this span
                        let remaining_width = target_width - accumulated_width;
                        if remaining_width > 0.0 {
                            let truncated =
                                self.truncate_text_to_width(ui, &text_span.text, remaining_width);
                            if !truncated.is_empty() {
                                result.push(ContentSpan::text(truncated, text_span.color.clone()));
                            }
                        }
                        // Add ellipsis and stop
                        result.push(ContentSpan::text(
                            ellipsis.to_string(),
                            text_span.color.clone(),
                        ));
                        return result;
                    }
                }
                // Icons are not truncated - either include fully or stop before them
                ContentSpan::RuneIcons | ContentSpan::KindlingIcon | ContentSpan::DeathIcon => {
                    let span_width = self.calculate_spans_width(ui, &[span.clone()]);

                    if accumulated_width + span_width <= target_width {
                        result.push(span.clone());
                        accumulated_width += span_width;
                    } else {
                        // Icon doesn't fit, add ellipsis and stop
                        result.push(ContentSpan::text(
                            ellipsis.to_string(),
                            TemplateColor::Default,
                        ));
                        return result;
                    }
                }
            }
        }

        // We processed all spans but need ellipsis (shouldn't happen if logic is correct)
        result
    }

    /// Truncate text to fit within a maximum width (without ellipsis)
    fn truncate_text_to_width(
        &self,
        ui: &hudhook::imgui::Ui,
        text: &str,
        max_width: f32,
    ) -> String {
        // Binary search for the longest prefix that fits
        let chars: Vec<char> = text.chars().collect();
        let mut low = 0;
        let mut high = chars.len();

        while low < high {
            let mid = (low + high + 1) / 2;
            let prefix: String = chars[..mid].iter().collect();
            let width = ui.calc_text_size(&prefix)[0];

            if width <= max_width {
                low = mid;
            } else {
                high = mid - 1;
            }
        }

        chars[..low].iter().collect()
    }

    /// Render a sequence of content spans (text and images)
    fn render_content_spans(&self, ui: &hudhook::imgui::Ui, spans: &[ContentSpan]) {
        let icon_size = self.icon_size();
        let font_height = ui.text_line_height();

        // Check if line has any icons to determine if vertical centering is needed
        let has_icons = spans.iter().any(|s| {
            matches!(
                s,
                ContentSpan::RuneIcons | ContentSpan::KindlingIcon | ContentSpan::DeathIcon
            )
        });

        // Calculate vertical offsets for centering
        let (text_y_offset, icon_y_offset) = if has_icons {
            let line_height = icon_size.max(font_height);
            (
                (line_height - font_height) / 2.0,
                (line_height - icon_size) / 2.0,
            )
        } else {
            (0.0, 0.0)
        };

        let mut first = true;
        let start_y = ui.cursor_pos()[1];

        for span in spans {
            match span {
                ContentSpan::Text(text_span) => {
                    if text_span.text.is_empty() {
                        continue;
                    }

                    if !first {
                        ui.same_line_with_spacing(0.0, 0.0);
                    }
                    first = false;

                    // Apply vertical offset for centering text
                    if text_y_offset > 0.0 {
                        let [x, _] = ui.cursor_pos();
                        ui.set_cursor_pos([x, start_y + text_y_offset]);
                    }

                    let color = self.resolve_template_color(&text_span.color);
                    ui.text_colored(color, &text_span.text);
                }
                ContentSpan::RuneIcons => {
                    if !first {
                        ui.same_line_with_spacing(0.0, 0.0);
                    }
                    first = false;

                    // Apply vertical offset for centering icons
                    if icon_y_offset > 0.0 {
                        let [x, _] = ui.cursor_pos();
                        ui.set_cursor_pos([x, start_y + icon_y_offset]);
                    }

                    self.render_rune_icons(ui, start_y + icon_y_offset);
                }
                ContentSpan::KindlingIcon => {
                    if !first {
                        ui.same_line_with_spacing(0.0, 0.0);
                    }
                    first = false;

                    if icon_y_offset > 0.0 {
                        let [x, _] = ui.cursor_pos();
                        ui.set_cursor_pos([x, start_y + icon_y_offset]);
                    }

                    self.render_kindling_icon(ui);
                }
                ContentSpan::DeathIcon => {
                    if !first {
                        ui.same_line_with_spacing(0.0, 0.0);
                    }
                    first = false;

                    if icon_y_offset > 0.0 {
                        let [x, _] = ui.cursor_pos();
                        ui.set_cursor_pos([x, start_y + icon_y_offset]);
                    }

                    self.render_death_icon(ui);
                }
            }
        }

        // Handle empty case (need to output something for line to register)
        if first {
            ui.text("");
        }
    }

    /// Render the 7 Great Rune icons
    fn render_rune_icons(&self, ui: &hudhook::imgui::Ui, target_y: f32) {
        let Some(ref atlas) = self.icon_atlas else {
            // Fallback: show text placeholder if atlas not loaded
            ui.text_disabled("[runes]");
            return;
        };

        let possessed = self.read_great_runes();
        let icon_size = self.icon_size();

        let mut first_icon = true;

        for rune in IconAtlas::runes_in_order() {
            let is_possessed = possessed.as_ref().is_some_and(|set| set.contains(&rune));
            let (uv0, uv1) = atlas.get_rune_uvs(rune, is_possessed);

            if !first_icon {
                ui.same_line_with_spacing(0.0, 2.0); // 2px spacing between icons
                                                     // Restore Y position after same_line (which resets to line start)
                let [x, _] = ui.cursor_pos();
                ui.set_cursor_pos([x, target_y]);
            }
            first_icon = false;

            Image::new(atlas.texture_id(), [icon_size, icon_size])
                .uv0(uv0)
                .uv1(uv1)
                .build(ui);
        }
    }

    /// Render the Kindling icon
    fn render_kindling_icon(&self, ui: &hudhook::imgui::Ui) {
        let Some(ref atlas) = self.icon_atlas else {
            // Fallback: show text placeholder if atlas not loaded
            ui.text_disabled("[K]");
            return;
        };

        let icon_size = self.icon_size();
        let (uv0, uv1) = atlas.get_kindling_uvs();
        Image::new(atlas.texture_id(), [icon_size, icon_size])
            .uv0(uv0)
            .uv1(uv1)
            .build(ui);
    }

    /// Render the Death icon
    fn render_death_icon(&self, ui: &hudhook::imgui::Ui) {
        let Some(ref atlas) = self.icon_atlas else {
            // Fallback: show text placeholder if atlas not loaded
            ui.text_disabled("[D]");
            return;
        };

        let icon_size = self.icon_size();
        let (uv0, uv1) = atlas.get_death_uvs();
        Image::new(atlas.texture_id(), [icon_size, icon_size])
            .uv0(uv0)
            .uv1(uv1)
            .build(ui);
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
    ///
    /// `max_exits` limits how many exits to show. If Some(n), only n exits are shown
    /// and a "+ X others" line is added. If None, all exits are shown.
    fn render_exits_section(&self, ui: &hudhook::imgui::Ui, max_exits: Option<usize>) {
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

        // Filter exits if undiscovered-only mode is active
        // Always sort undiscovered exits first
        let mut exits_to_show: Vec<_> = if self.show_undiscovered_only {
            self.current_exits()
                .iter()
                .filter(|e| e.target == "???")
                .collect()
        } else {
            self.current_exits().iter().collect()
        };
        exits_to_show.sort_by_key(|e| e.target != "???");

        // Show filter indicator when undiscovered-only mode is active
        if self.show_undiscovered_only {
            let total_undiscovered = exits_to_show.len();
            let hotkey = self.config.keybindings.toggle_undiscovered_only.name();
            ui.text_disabled(format!(
                "[Undiscovered only: {} exits] ({} to show all)",
                total_undiscovered, hotkey
            ));
        }

        // Determine how many exits to display
        let total_exits = exits_to_show.len();
        let display_count = max_exits.unwrap_or(total_exits).min(total_exits);
        let truncated = display_count < total_exits;

        for exit in exits_to_show.iter().take(display_count) {
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

        // Show truncation indicator
        if truncated {
            let remaining = total_exits - display_count;
            ui.text_disabled(format!(
                "  + {} other{}",
                remaining,
                if remaining > 1 { "s" } else { "" }
            ));
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
