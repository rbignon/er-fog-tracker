// Main launcher application using egui

use eframe::egui;
use std::path::PathBuf;
use std::sync::mpsc::{channel, Receiver, Sender};
use std::thread;

use super::api_client::{ApiClient, ApiError, GameSummary, UserInfo};
use super::config::LauncherConfig;
use super::process_monitor::{find_dll_path, ProcessMonitor, ProcessState};
use super::spoiler_validator::{
    read_spoiler_file, validate_spoiler_file, SpoilerHeader, ValidationError,
};

// =============================================================================
// Application State
// =============================================================================

#[derive(Debug)]
pub enum AppState {
    /// Waiting for user to enter server URL and mod token
    TokenInput {
        server_url: String,
        token: String,
        error: Option<String>,
        validating: bool,
    },
    /// Game selection screen
    GameSelection {
        user: UserInfo,
        games: Vec<GameSummary>,
        selected_index: Option<usize>,
        loading: bool,
        error: Option<String>,
    },
    /// Creating a new game
    NewGame {
        user: UserInfo,
        label: String,
        spoiler_path: Option<PathBuf>,
        validation: Option<Result<SpoilerHeader, ValidationError>>,
        creating: bool,
        error: Option<String>,
    },
    /// Waiting for Elden Ring process
    WaitingForGame { user: UserInfo, game: GameSummary },
    /// Mod has been injected
    Injected { user: UserInfo, game: GameSummary },
}

// =============================================================================
// Background Task Messages
// =============================================================================

enum TaskResult {
    TokenValidated(Result<UserInfo, ApiError>),
    GamesLoaded(Result<Vec<GameSummary>, ApiError>),
    GameCreated(Result<(GameSummary, bool), ApiError>),
}

// =============================================================================
// Launcher App
// =============================================================================

pub struct LauncherApp {
    state: AppState,
    config: LauncherConfig,
    process_monitor: Option<ProcessMonitor>,
    task_sender: Sender<TaskResult>,
    task_receiver: Receiver<TaskResult>,
    dll_path: Option<PathBuf>,
    dll_error: Option<String>,
}

impl LauncherApp {
    pub fn new(_cc: &eframe::CreationContext<'_>) -> Self {
        let (task_sender, task_receiver) = channel();
        let config = LauncherConfig::load();

        // Find DLL path
        let dll_path = find_dll_path();
        let dll_error = if dll_path.is_none() {
            Some("fog_rando_tracker.dll not found".to_string())
        } else {
            None
        };

        // Initialize process monitor if DLL found
        let process_monitor = dll_path.clone().map(ProcessMonitor::new);

        // Determine initial state based on config
        let state = if config.has_token() {
            // Start validating the saved token
            let token = config.mod_token.clone().unwrap();
            let url = config.server_url.clone();
            let sender = task_sender.clone();

            thread::spawn(move || {
                let client = ApiClient::new(&url, &token);
                let result = client.validate_token();
                let _ = sender.send(TaskResult::TokenValidated(result));
            });

            AppState::TokenInput {
                server_url: config.server_url.clone(),
                token: config.mod_token.clone().unwrap_or_default(),
                error: None,
                validating: true,
            }
        } else {
            AppState::TokenInput {
                server_url: config.server_url.clone(),
                token: String::new(),
                error: None,
                validating: false,
            }
        };

        Self {
            state,
            config,
            process_monitor,
            task_sender,
            task_receiver,
            dll_path,
            dll_error,
        }
    }

    fn validate_token(&mut self, url: String, token: String) {
        let sender = self.task_sender.clone();

        thread::spawn(move || {
            let client = ApiClient::new(&url, &token);
            let result = client.validate_token();
            let _ = sender.send(TaskResult::TokenValidated(result));
        });
    }

    fn load_games(&mut self) {
        let url = self.config.server_url.clone();
        let token = self.config.mod_token.clone().unwrap_or_default();
        let sender = self.task_sender.clone();

        thread::spawn(move || {
            let client = ApiClient::new(&url, &token);
            let result = client.list_games();
            let _ = sender.send(TaskResult::GamesLoaded(result));
        });
    }

    fn create_game(&mut self, spoiler_content: String, label: Option<String>) {
        let url = self.config.server_url.clone();
        let token = self.config.mod_token.clone().unwrap_or_default();
        let sender = self.task_sender.clone();

        thread::spawn(move || {
            let client = ApiClient::new(&url, &token);
            let result = client.create_game(&spoiler_content, label.as_deref());

            // If created, fetch game list to get full game info
            let result = result.and_then(|resp| {
                let games = client.list_games()?;
                let game = games
                    .into_iter()
                    .find(|g| g.id == resp.game_id)
                    .ok_or(ApiError::NotFound)?;
                Ok((game, resp.created))
            });

            let _ = sender.send(TaskResult::GameCreated(result));
        });
    }

    fn process_tasks(&mut self) {
        while let Ok(result) = self.task_receiver.try_recv() {
            match result {
                TaskResult::TokenValidated(Ok(user)) => {
                    // Token is valid, save it and load games
                    if let AppState::TokenInput {
                        server_url, token, ..
                    } = &self.state
                    {
                        self.config.server_url = server_url.clone();
                        self.config.mod_token = Some(token.clone());
                        let _ = self.config.save();
                    }

                    self.state = AppState::GameSelection {
                        user,
                        games: vec![],
                        selected_index: None,
                        loading: true,
                        error: None,
                    };
                    self.load_games();
                }
                TaskResult::TokenValidated(Err(e)) => {
                    self.state = AppState::TokenInput {
                        server_url: self.config.server_url.clone(),
                        token: self.config.mod_token.clone().unwrap_or_default(),
                        error: Some(e.to_string()),
                        validating: false,
                    };
                }
                TaskResult::GamesLoaded(Ok(games)) => {
                    if let AppState::GameSelection { user, .. } = &self.state {
                        // Pre-select last used game if available
                        let selected_index = self
                            .config
                            .last_game_id
                            .as_ref()
                            .and_then(|last_id| games.iter().position(|g| g.id == *last_id));

                        self.state = AppState::GameSelection {
                            user: user.clone(),
                            games,
                            selected_index,
                            loading: false,
                            error: None,
                        };
                    }
                }
                TaskResult::GamesLoaded(Err(e)) => {
                    if let AppState::GameSelection { user, .. } = &self.state {
                        self.state = AppState::GameSelection {
                            user: user.clone(),
                            games: vec![],
                            selected_index: None,
                            loading: false,
                            error: Some(e.to_string()),
                        };
                    }
                }
                TaskResult::GameCreated(Ok((game, _created))) => {
                    if let AppState::NewGame { user, .. } = &self.state {
                        // Save as last game and go to waiting state
                        self.config.last_game_id = Some(game.id.clone());
                        let _ = self.config.save();

                        self.state = AppState::WaitingForGame {
                            user: user.clone(),
                            game,
                        };
                    }
                }
                TaskResult::GameCreated(Err(e)) => {
                    if let AppState::NewGame {
                        user,
                        label,
                        spoiler_path,
                        validation,
                        ..
                    } = &self.state
                    {
                        self.state = AppState::NewGame {
                            user: user.clone(),
                            label: label.clone(),
                            spoiler_path: spoiler_path.clone(),
                            validation: validation.clone(),
                            creating: false,
                            error: Some(e.to_string()),
                        };
                    }
                }
            }
        }
    }

    fn poll_process(&mut self) {
        if let Some(ref mut monitor) = self.process_monitor {
            let state_changed = monitor.poll();

            match (&self.state, monitor.state()) {
                // In waiting state and process is ready to inject
                (AppState::WaitingForGame { .. }, ProcessState::Running)
                    if monitor.ready_to_inject() =>
                {
                    match monitor.inject() {
                        Ok(()) => {
                            if let AppState::WaitingForGame { user, game } = &self.state {
                                self.state = AppState::Injected {
                                    user: user.clone(),
                                    game: game.clone(),
                                };
                            }
                        }
                        Err(e) => {
                            // TODO: Show injection error
                            eprintln!("Injection failed: {}", e);
                        }
                    }
                }
                // In injected state and process exited
                (AppState::Injected { user, .. }, ProcessState::NotRunning) => {
                    // Go back to game selection
                    self.state = AppState::GameSelection {
                        user: user.clone(),
                        games: vec![],
                        selected_index: None,
                        loading: true,
                        error: None,
                    };
                    self.load_games();
                }
                _ => {}
            }

            // Request repaint if state might change
            if state_changed || matches!(self.state, AppState::WaitingForGame { .. }) {
                // Will be handled by continuous repaint in update()
            }
        }
    }
}

impl eframe::App for LauncherApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        // Process background tasks
        self.process_tasks();

        // Poll process monitor
        self.poll_process();

        // Request continuous repaint when waiting for process
        if matches!(
            self.state,
            AppState::WaitingForGame { .. } | AppState::Injected { .. }
        ) {
            ctx.request_repaint_after(std::time::Duration::from_millis(500));
        }

        egui::CentralPanel::default().show(ctx, |ui| {
            // Show DLL error if present
            if let Some(ref error) = self.dll_error {
                ui.horizontal(|ui| {
                    ui.label(egui::RichText::new("⚠").color(egui::Color32::YELLOW));
                    ui.label(error);
                });
                ui.separator();
            }

            match &mut self.state {
                AppState::TokenInput { .. } => self.render_token_input(ui),
                AppState::GameSelection { .. } => self.render_game_selection(ui),
                AppState::NewGame { .. } => self.render_new_game(ui),
                AppState::WaitingForGame { .. } => self.render_waiting(ui),
                AppState::Injected { .. } => self.render_injected(ui),
            }
        });
    }
}

// =============================================================================
// UI Rendering
// =============================================================================

impl LauncherApp {
    fn render_token_input(&mut self, ui: &mut egui::Ui) {
        // Clone state upfront to avoid borrow issues
        let (mut server_url, mut token, error, validating) = match &self.state {
            AppState::TokenInput {
                server_url,
                token,
                error,
                validating,
            } => (
                server_url.clone(),
                token.clone(),
                error.clone(),
                *validating,
            ),
            _ => return,
        };

        // Track changes
        let mut should_validate = false;
        let server_url_before = server_url.clone();
        let token_before = token.clone();

        ui.vertical_centered(|ui| {
            ui.add_space(20.0);
            ui.heading("🔗 Server Configuration");
            ui.add_space(15.0);

            // Server URL field
            ui.label("Server URL:");
            ui.add_space(5.0);
            ui.add(
                egui::TextEdit::singleline(&mut server_url)
                    .desired_width(400.0)
                    .hint_text("https://fog-vizu.example.com"),
            );

            ui.add_space(20.0);
            ui.separator();
            ui.add_space(20.0);

            ui.heading("🔑 Mod Token");
            ui.add_space(15.0);

            ui.label("Enter your mod token:");
            ui.add_space(5.0);

            let response = ui.add(
                egui::TextEdit::singleline(&mut token)
                    .password(true)
                    .desired_width(400.0)
                    .hint_text("Paste your mod token here..."),
            );

            if let Some(ref err) = error {
                ui.add_space(5.0);
                ui.label(egui::RichText::new(err.as_str()).color(egui::Color32::RED));
            }

            ui.add_space(10.0);
            ui.label(
                egui::RichText::new("ℹ Find your token in Settings on the fog-vizu website").weak(),
            );

            ui.add_space(20.0);

            let button_text = if validating {
                "Validating..."
            } else {
                "Save & Continue"
            };
            let can_validate = !validating && !token.is_empty() && !server_url.is_empty();
            let button = ui.add_enabled(can_validate, egui::Button::new(button_text));

            if button.clicked()
                || (response.lost_focus() && ui.input(|i| i.key_pressed(egui::Key::Enter)))
            {
                if can_validate {
                    should_validate = true;
                }
            }
        });

        // Apply changes after rendering

        // Update server_url if changed
        if server_url != server_url_before {
            if let AppState::TokenInput { server_url: u, .. } = &mut self.state {
                *u = server_url.clone();
            }
        }

        // Update token if changed
        if token != token_before {
            if let AppState::TokenInput { token: t, .. } = &mut self.state {
                *t = token.clone();
            }
        }

        // Start validation if requested
        if should_validate {
            self.state = AppState::TokenInput {
                server_url: server_url.clone(),
                token: token.clone(),
                error: None,
                validating: true,
            };
            self.validate_token(server_url, token);
        }
    }

    fn render_game_selection(&mut self, ui: &mut egui::Ui) {
        // Extract state - we need to clone to avoid borrow issues
        let (user, games, selected_index, loading, error) = match &self.state {
            AppState::GameSelection {
                user,
                games,
                selected_index,
                loading,
                error,
            } => (
                user.clone(),
                games.clone(),
                *selected_index,
                *loading,
                error.clone(),
            ),
            _ => return,
        };

        // Header
        ui.horizontal(|ui| {
            ui.label(format!(
                "Connected as: {}",
                user.display_name.as_ref().unwrap_or(&user.username)
            ));
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                if ui.small_button("Change Token").clicked() {
                    self.config.mod_token = None;
                    let _ = self.config.save();
                    self.state = AppState::TokenInput {
                        server_url: self.config.server_url.clone(),
                        token: String::new(),
                        error: None,
                        validating: false,
                    };
                }
            });
        });
        ui.separator();

        // Error display
        if let Some(err) = &error {
            ui.label(egui::RichText::new(err).color(egui::Color32::RED));
            ui.add_space(5.0);
        }

        // Loading indicator
        if loading {
            ui.horizontal(|ui| {
                ui.spinner();
                ui.label("Loading games...");
            });
            return;
        }

        ui.label("Select a game:");
        ui.add_space(5.0);

        // Game list
        let mut new_selected = selected_index;
        egui::ScrollArea::vertical()
            .max_height(300.0)
            .show(ui, |ui| {
                for (i, game) in games.iter().enumerate() {
                    let is_selected = selected_index == Some(i);

                    // Game item as a selectable frame
                    let response = egui::Frame::none()
                        .inner_margin(egui::Margin::symmetric(4.0, 2.0))
                        .show(ui, |ui| {
                            ui.horizontal(|ui| {
                                ui.radio(is_selected, "");
                                ui.vertical(|ui| {
                                    ui.label(egui::RichText::new(game.display_name()).strong());
                                    ui.label(
                                        egui::RichText::new(format!(
                                            "Seed: {} • {} • {}",
                                            game.seed,
                                            game.progress_text(),
                                            game.relative_time()
                                        ))
                                        .weak()
                                        .small(),
                                    );
                                });
                            });
                        })
                        .response;

                    if response.interact(egui::Sense::click()).clicked() {
                        new_selected = Some(i);
                    }
                }
            });

        // Update selection if changed
        if new_selected != selected_index {
            self.state = AppState::GameSelection {
                user: user.clone(),
                games: games.clone(),
                selected_index: new_selected,
                loading: false,
                error: None,
            };
        }

        ui.add_space(10.0);

        // New game button
        if ui.button("+ New Game").clicked() {
            self.state = AppState::NewGame {
                user: user.clone(),
                label: String::new(),
                spoiler_path: None,
                validation: None,
                creating: false,
                error: None,
            };
        }

        ui.add_space(10.0);
        ui.separator();

        // Inject button
        ui.horizontal(|ui| {
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                let can_inject = selected_index.is_some() && self.dll_path.is_some();
                let inject_btn = ui.add_enabled(can_inject, egui::Button::new("▶ Inject"));

                if inject_btn.clicked() {
                    if let Some(idx) = selected_index {
                        if let Some(game) = games.get(idx) {
                            // Save selected game
                            self.config.last_game_id = Some(game.id.clone());
                            let _ = self.config.save();

                            // Reset process monitor
                            if let Some(ref mut monitor) = self.process_monitor {
                                monitor.reset();
                            }

                            self.state = AppState::WaitingForGame {
                                user: user.clone(),
                                game: game.clone(),
                            };
                        }
                    }
                }
            });
        });
    }

    fn render_new_game(&mut self, ui: &mut egui::Ui) {
        // Clone all state upfront to avoid borrow issues
        let (user, mut label, spoiler_path, validation, creating, error) = match &self.state {
            AppState::NewGame {
                user,
                label,
                spoiler_path,
                validation,
                creating,
                error,
            } => (
                user.clone(),
                label.clone(),
                spoiler_path.clone(),
                validation.clone(),
                *creating,
                error.clone(),
            ),
            _ => return,
        };

        // Track changes - label can change independently of button actions
        let mut label_changed = false;
        let mut new_file: Option<(PathBuf, Result<SpoilerHeader, ValidationError>)> = None;
        let mut cancel_clicked = false;
        let mut create_result: Option<Result<(String, Option<String>), String>> = None;

        ui.heading("New Game");
        ui.add_space(10.0);

        // Error display
        if let Some(ref err) = error {
            ui.label(egui::RichText::new(err.as_str()).color(egui::Color32::RED));
            ui.add_space(5.0);
        }

        // Label input
        ui.label("Label (optional):");
        let label_before = label.clone();
        ui.text_edit_singleline(&mut label);
        if label != label_before {
            label_changed = true;
        }
        ui.add_space(10.0);

        // Spoiler log selection
        ui.label("Spoiler Log:");
        ui.horizontal(|ui| {
            let path_text = spoiler_path
                .as_ref()
                .map(|p| p.display().to_string())
                .unwrap_or_else(|| "No file selected".to_string());

            ui.label(&path_text);

            if ui.button("Browse...").clicked() {
                if let Some(path) = rfd::FileDialog::new()
                    .add_filter("Spoiler Log", &["txt"])
                    .pick_file()
                {
                    let validation_result = validate_spoiler_file(&path);
                    new_file = Some((path, validation_result));
                }
            }
        });

        // Validation status
        if let Some(ref result) = validation {
            ui.add_space(5.0);
            match result {
                Ok(header) => {
                    ui.label(
                        egui::RichText::new(format!("✓ Valid spoiler log (Seed: {})", header.seed))
                            .color(egui::Color32::GREEN),
                    );
                }
                Err(e) => {
                    ui.label(egui::RichText::new(format!("✗ {}", e)).color(egui::Color32::RED));
                }
            }
        }

        ui.add_space(20.0);

        // Buttons
        ui.horizontal(|ui| {
            if ui.button("Cancel").clicked() {
                cancel_clicked = true;
            }

            let can_create = validation.as_ref().map(|v| v.is_ok()).unwrap_or(false) && !creating;

            let create_text = if creating {
                "Creating..."
            } else {
                "Create Game"
            };
            let create_btn = ui.add_enabled(can_create, egui::Button::new(create_text));

            if create_btn.clicked() {
                if let Some(ref path) = spoiler_path {
                    match read_spoiler_file(path) {
                        Ok(content) => {
                            let label_opt = if label.is_empty() {
                                None
                            } else {
                                Some(label.clone())
                            };
                            create_result = Some(Ok((content, label_opt)));
                        }
                        Err(e) => {
                            create_result = Some(Err(e.to_string()));
                        }
                    }
                }
            }
        });

        // Apply changes after rendering

        // Always update label if changed (even if other actions happen)
        if label_changed {
            if let AppState::NewGame { label: l, .. } = &mut self.state {
                *l = label.clone();
            }
        }

        // Apply file selection
        if let Some((path, validation_result)) = new_file {
            if let AppState::NewGame {
                spoiler_path: sp,
                validation: v,
                ..
            } = &mut self.state
            {
                *sp = Some(path);
                *v = Some(validation_result);
            }
        }

        // Handle cancel
        if cancel_clicked {
            self.state = AppState::GameSelection {
                user,
                games: vec![],
                selected_index: None,
                loading: true,
                error: None,
            };
            self.load_games();
            return;
        }

        // Handle create
        if let Some(result) = create_result {
            match result {
                Ok((content, label_opt)) => {
                    if let AppState::NewGame { creating: c, .. } = &mut self.state {
                        *c = true;
                    }
                    self.create_game(content, label_opt);
                }
                Err(err) => {
                    if let AppState::NewGame { error: e, .. } = &mut self.state {
                        *e = Some(err);
                    }
                }
            }
        }
    }

    fn render_waiting(&mut self, ui: &mut egui::Ui) {
        let (user, game) = match &self.state {
            AppState::WaitingForGame { user, game } => (user.clone(), game.clone()),
            _ => return,
        };

        ui.horizontal(|ui| {
            ui.label(format!(
                "Connected as: {}",
                user.display_name.as_ref().unwrap_or(&user.username)
            ));
        });
        ui.separator();

        ui.vertical_centered(|ui| {
            ui.add_space(40.0);

            ui.label(format!(
                "Selected: {} (Seed: {})",
                game.display_name(),
                game.seed
            ));
            ui.add_space(20.0);

            ui.spinner();
            ui.add_space(10.0);

            // Show status based on process monitor state
            if let Some(ref monitor) = self.process_monitor {
                match monitor.state() {
                    ProcessState::NotRunning => {
                        ui.heading("Waiting for Elden Ring...");
                        ui.label("Please launch the game.");
                    }
                    ProcessState::Running => {
                        if let Some(remaining) = monitor.time_until_ready() {
                            ui.heading("Game detected!");
                            ui.label(format!(
                                "Injecting in {} seconds...",
                                remaining.as_secs() + 1
                            ));
                        } else {
                            ui.heading("Injecting...");
                        }
                    }
                    ProcessState::Injected => {
                        ui.heading("Injected!");
                    }
                }
            } else {
                ui.heading("Waiting for Elden Ring...");
                ui.label("Please launch the game.");
            }

            ui.add_space(40.0);
        });

        ui.separator();
        ui.horizontal(|ui| {
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                if ui.button("Cancel").clicked() {
                    if let Some(ref mut monitor) = self.process_monitor {
                        monitor.reset();
                    }
                    self.state = AppState::GameSelection {
                        user,
                        games: vec![],
                        selected_index: None,
                        loading: true,
                        error: None,
                    };
                    self.load_games();
                }
            });
        });
    }

    fn render_injected(&mut self, ui: &mut egui::Ui) {
        let (user, game) = match &self.state {
            AppState::Injected { user, game } => (user.clone(), game.clone()),
            _ => return,
        };

        ui.horizontal(|ui| {
            ui.label(format!(
                "Connected as: {}",
                user.display_name.as_ref().unwrap_or(&user.username)
            ));
        });
        ui.separator();

        ui.vertical_centered(|ui| {
            ui.add_space(40.0);

            ui.heading(egui::RichText::new("✓ Mod Active").color(egui::Color32::GREEN));
            ui.add_space(20.0);

            ui.label(format!("Game: {}", game.display_name()));
            ui.label(format!("Seed: {}", game.seed));

            ui.add_space(20.0);
            ui.separator();
            ui.add_space(20.0);

            ui.label("Press F9 in-game to toggle the overlay.");
            ui.add_space(10.0);
            ui.label(egui::RichText::new("This window will unlock when the game closes.").weak());
        });

        ui.add_space(40.0);
        ui.separator();

        ui.horizontal(|ui| {
            ui.label(egui::RichText::new("● Game running").color(egui::Color32::GREEN));
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                if ui.button("Minimize").clicked() {
                    // TODO: Minimize to tray or taskbar
                }
            });
        });
    }
}
