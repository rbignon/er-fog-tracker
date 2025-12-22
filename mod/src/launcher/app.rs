// Main launcher application using native-windows-gui

extern crate native_windows_derive as nwd;
extern crate native_windows_gui as nwg;

use nwd::NwgUi;
use nwg::NativeUi;
use std::cell::RefCell;
use std::path::PathBuf;
use std::sync::mpsc::{channel, Receiver, Sender};
use std::thread;
use std::time::Duration;

use super::api_client::{ApiClient, ApiError, GameSummary, UserInfo};
use super::config::LauncherConfig;
use super::process_monitor::{find_dll_path, ProcessMonitor, ProcessState};
use super::rando_folder::{
    entity_mapping_to_json, extract_rando_data, validate_rando_folder, RandoFolderData,
    ValidatedRandoFolder,
};

// =============================================================================
// Application State
// =============================================================================

#[derive(Debug, Clone, PartialEq)]
pub enum AppScreen {
    TokenInput,
    GameSelection,
    WaitingForGame,
    Injected,
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
// Application Data (non-UI state)
// =============================================================================

struct AppData {
    config: LauncherConfig,
    current_screen: AppScreen,
    user: Option<UserInfo>,
    games: Vec<GameSummary>,
    selected_game: Option<GameSummary>,
    rando_folder: Option<ValidatedRandoFolder>,
    rando_valid: bool,
    process_monitor: Option<ProcessMonitor>,
    task_sender: Sender<TaskResult>,
    task_receiver: Receiver<TaskResult>,
}

impl AppData {
    fn new() -> Self {
        let (task_sender, task_receiver) = channel();
        let config = LauncherConfig::load();
        let dll_path = find_dll_path();
        let process_monitor = dll_path.map(ProcessMonitor::new);

        Self {
            config,
            current_screen: AppScreen::TokenInput,
            user: None,
            games: vec![],
            selected_game: None,
            rando_folder: None,
            rando_valid: false,
            process_monitor,
            task_sender,
            task_receiver,
        }
    }

    fn validate_token(&self, url: String, token: String) {
        let sender = self.task_sender.clone();
        thread::spawn(move || {
            let client = ApiClient::new(&url, &token);
            let result = client.validate_token();
            let _ = sender.send(TaskResult::TokenValidated(result));
        });
    }

    fn load_games(&self) {
        let url = self.config.server_url.clone();
        let token = self.config.mod_token.clone().unwrap_or_default();
        let sender = self.task_sender.clone();
        thread::spawn(move || {
            let client = ApiClient::new(&url, &token);
            let result = client.list_games();
            let _ = sender.send(TaskResult::GamesLoaded(result));
        });
    }

    fn create_game(&self, rando_data: RandoFolderData, label: Option<String>) {
        let url = self.config.server_url.clone();
        let token = self.config.mod_token.clone().unwrap_or_default();
        let sender = self.task_sender.clone();
        thread::spawn(move || {
            let client = ApiClient::new(&url, &token);
            let entity_mapping = Some(entity_mapping_to_json(&rando_data.entity_mapping));
            let result = client.create_game(
                &rando_data.spoiler_content,
                label.as_deref(),
                entity_mapping,
            );
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
}

// =============================================================================
// Main Application UI
// =============================================================================

#[derive(Default, NwgUi)]
pub struct LauncherApp {
    #[nwg_control(size: (500, 450), position: (300, 200), title: "FogRandoTracker Launcher")]
    #[nwg_events(OnWindowClose: [LauncherApp::on_exit])]
    window: nwg::Window,

    #[nwg_control(parent: window, interval: Duration::from_millis(500), active: false)]
    #[nwg_events(OnTick: [LauncherApp::on_timer])]
    timer: nwg::AnimationTimer,

    // =========================================================================
    // Token Input Screen
    // =========================================================================
    #[nwg_control(parent: window, text: "Server URL:", position: (20, 20), size: (460, 20))]
    token_url_label: nwg::Label,

    #[nwg_control(parent: window, text: "", position: (20, 45), size: (460, 25))]
    token_url_input: nwg::TextInput,

    #[nwg_control(parent: window, text: "Mod Token:", position: (20, 85), size: (460, 20))]
    token_label: nwg::Label,

    #[nwg_control(parent: window, text: "", position: (20, 110), size: (460, 25), flags: "VISIBLE|TAB_STOP")]
    token_input: nwg::TextInput,

    #[nwg_control(parent: window, text: "Find your token in Settings on the fog-vizu website", position: (20, 145), size: (460, 20))]
    token_hint: nwg::Label,

    #[nwg_control(parent: window, text: "", position: (20, 175), size: (460, 40))]
    token_error: nwg::Label,

    #[nwg_control(parent: window, text: "Connect", position: (200, 230), size: (100, 35))]
    #[nwg_events(OnButtonClick: [LauncherApp::on_connect_click])]
    token_connect_btn: nwg::Button,

    // =========================================================================
    // Game Selection Screen
    // =========================================================================
    #[nwg_control(parent: window, text: "Connected as: ", position: (20, 20), size: (350, 20))]
    games_user_label: nwg::Label,

    #[nwg_control(parent: window, text: "Change Token", position: (380, 15), size: (100, 30))]
    #[nwg_events(OnButtonClick: [LauncherApp::on_change_token_click])]
    games_change_token_btn: nwg::Button,

    #[nwg_control(parent: window, text: "Select a game:", position: (20, 55), size: (460, 20))]
    games_list_label: nwg::Label,

    #[nwg_control(parent: window, position: (20, 80), size: (460, 200), list_style: nwg::ListViewStyle::Detailed, ex_flags: nwg::ListViewExFlags::FULL_ROW_SELECT)]
    #[nwg_events(OnListViewItemChanged: [LauncherApp::on_game_selected])]
    games_list: nwg::ListView,

    #[nwg_control(parent: window, text: "New Game", position: (20, 290), size: (100, 35))]
    #[nwg_events(OnButtonClick: [LauncherApp::on_new_game_click])]
    games_new_btn: nwg::Button,

    #[nwg_control(parent: window, text: "Inject", position: (200, 350), size: (100, 40))]
    #[nwg_events(OnButtonClick: [LauncherApp::on_inject_click])]
    games_inject_btn: nwg::Button,

    #[nwg_control(parent: window, text: "", position: (20, 335), size: (170, 25))]
    games_status: nwg::Label,

    // =========================================================================
    // New Game Dialog (separate popup window)
    // =========================================================================
    #[nwg_control(size: (420, 320), position: (350, 250), title: "New Game", flags: "WINDOW")]
    #[nwg_events(OnWindowClose: [LauncherApp::on_newgame_dialog_close])]
    newgame_window: nwg::Window,

    #[nwg_control(parent: newgame_window, text: "Label (optional):", position: (20, 20), size: (380, 20))]
    newgame_label_label: nwg::Label,

    #[nwg_control(parent: newgame_window, text: "", position: (20, 45), size: (380, 25))]
    newgame_label_input: nwg::TextInput,

    #[nwg_control(parent: newgame_window, text: "Randomizer Folder:", position: (20, 90), size: (380, 20))]
    newgame_folder_label: nwg::Label,

    #[nwg_control(parent: newgame_window, text: "Browse...", position: (20, 115), size: (100, 30))]
    #[nwg_events(OnButtonClick: [LauncherApp::on_browse_folder_click])]
    newgame_browse_btn: nwg::Button,

    #[nwg_control(parent: newgame_window, text: "No folder selected", position: (130, 122), size: (270, 20))]
    newgame_folder_display: nwg::Label,

    #[nwg_control(parent: newgame_window, text: "", position: (20, 160), size: (380, 40))]
    newgame_validation: nwg::Label,

    #[nwg_control(parent: newgame_window, text: "", position: (20, 200), size: (380, 40))]
    newgame_error: nwg::Label,

    #[nwg_control(parent: newgame_window, text: "Cancel", position: (100, 250), size: (100, 35))]
    #[nwg_events(OnButtonClick: [LauncherApp::on_newgame_cancel_click])]
    newgame_cancel_btn: nwg::Button,

    #[nwg_control(parent: newgame_window, text: "Create", position: (220, 250), size: (100, 35))]
    #[nwg_events(OnButtonClick: [LauncherApp::on_newgame_create_click])]
    newgame_create_btn: nwg::Button,

    // =========================================================================
    // Waiting Screen
    // =========================================================================
    #[nwg_control(parent: window, text: "Waiting for Elden Ring...", position: (20, 100), size: (460, 30))]
    waiting_title: nwg::Label,

    #[nwg_control(parent: window, text: "", position: (20, 140), size: (460, 25))]
    waiting_game_label: nwg::Label,

    #[nwg_control(parent: window, text: "Please launch the game", position: (20, 180), size: (460, 25))]
    waiting_status: nwg::Label,

    #[nwg_control(parent: window, text: "Cancel", position: (200, 250), size: (100, 35))]
    #[nwg_events(OnButtonClick: [LauncherApp::on_waiting_cancel_click])]
    waiting_cancel_btn: nwg::Button,

    // =========================================================================
    // Injected Screen
    // =========================================================================
    #[nwg_control(parent: window, text: "Mod Active", position: (20, 80), size: (460, 30))]
    injected_title: nwg::Label,

    #[nwg_control(parent: window, text: "", position: (20, 130), size: (460, 25))]
    injected_game_label: nwg::Label,

    #[nwg_control(parent: window, text: "Press F9 in-game to toggle the overlay", position: (20, 180), size: (460, 25))]
    injected_hint: nwg::Label,

    #[nwg_control(parent: window, text: "", position: (20, 220), size: (460, 25))]
    injected_status: nwg::Label,

    #[nwg_control(parent: window, text: "Back to Games", position: (200, 280), size: (100, 35))]
    #[nwg_events(OnButtonClick: [LauncherApp::on_injected_back_click])]
    injected_back_btn: nwg::Button,

    // Application data
    data: RefCell<Option<AppData>>,
}

impl LauncherApp {
    fn init(&self) {
        let data = AppData::new();

        // Setup ListView columns
        self.games_list.insert_column("Name");
        self.games_list.insert_column("Seed");
        self.games_list.insert_column("Progress");
        self.games_list.set_column_width(0, 180);
        self.games_list.set_column_width(1, 120);
        self.games_list.set_column_width(2, 120);

        // Hide New Game dialog initially
        self.newgame_window.set_visible(false);

        // Load saved config
        self.token_url_input.set_text(&data.config.server_url);
        if let Some(ref token) = data.config.mod_token {
            self.token_input.set_text(token);
        }

        // Auto-validate if we have a token
        if data.config.has_token() {
            let url = data.config.server_url.clone();
            let token = data.config.mod_token.clone().unwrap();
            self.token_connect_btn.set_text("Connecting...");
            self.token_connect_btn.set_enabled(false);
            data.validate_token(url, token);
        }

        self.timer.start();
        *self.data.borrow_mut() = Some(data);
        self.show_screen(AppScreen::TokenInput);
    }

    fn on_exit(&self) {
        self.timer.stop();
        nwg::stop_thread_dispatch();
    }

    fn on_timer(&self) {
        let mut data_ref = self.data.borrow_mut();
        let data = match data_ref.as_mut() {
            Some(d) => d,
            None => return,
        };

        // Process async task results
        while let Ok(result) = data.task_receiver.try_recv() {
            match result {
                TaskResult::TokenValidated(Ok(user)) => {
                    data.config.server_url = self.token_url_input.text();
                    data.config.mod_token = Some(self.token_input.text());
                    let _ = data.config.save();
                    data.user = Some(user.clone());

                    let display = user.display_name.as_ref().unwrap_or(&user.username);
                    self.games_user_label
                        .set_text(&format!("Connected as: {}", display));

                    data.current_screen = AppScreen::GameSelection;
                    self.show_screen(AppScreen::GameSelection);
                    data.load_games();
                }
                TaskResult::TokenValidated(Err(e)) => {
                    self.token_error.set_text(&format!("Error: {}", e));
                    self.token_connect_btn.set_text("Connect");
                    self.token_connect_btn.set_enabled(true);
                }
                TaskResult::GamesLoaded(Ok(games)) => {
                    data.games = games.clone();
                    self.games_list.clear();
                    for game in &games {
                        let name = game.display_name();
                        let seed = game.seed.to_string();
                        let progress = game.progress_text();
                        self.games_list.insert_items_row(
                            None,
                            &[name.as_str(), seed.as_str(), progress.as_str()],
                        );
                    }
                    // Pre-select last game
                    if let Some(ref last_id) = data.config.last_game_id {
                        if let Some(idx) = games.iter().position(|g| &g.id == last_id) {
                            self.games_list.select_item(idx, true);
                            data.selected_game = games.get(idx).cloned();
                        }
                    }
                }
                TaskResult::GamesLoaded(Err(e)) => {
                    self.games_status.set_text(&format!("Error: {}", e));
                }
                TaskResult::GameCreated(Ok((game, _))) => {
                    // Close dialog first
                    self.newgame_window.set_visible(false);
                    self.window.set_enabled(true);

                    data.config.last_game_id = Some(game.id.clone());
                    let _ = data.config.save();
                    data.selected_game = Some(game.clone());
                    self.waiting_game_label.set_text(&format!(
                        "{} (Seed: {})",
                        game.display_name(),
                        game.seed
                    ));
                    data.current_screen = AppScreen::WaitingForGame;
                    self.show_screen(AppScreen::WaitingForGame);
                }
                TaskResult::GameCreated(Err(e)) => {
                    self.newgame_error.set_text(&format!("Error: {}", e));
                    self.newgame_create_btn.set_text("Create");
                    self.newgame_create_btn.set_enabled(data.rando_valid);
                }
            }
        }

        // Poll process monitor
        if data.current_screen == AppScreen::WaitingForGame
            || data.current_screen == AppScreen::Injected
        {
            if let Some(ref mut monitor) = data.process_monitor {
                monitor.poll();

                let monitor_state = monitor.state().clone();
                match (&data.current_screen, &monitor_state) {
                    (AppScreen::WaitingForGame, ProcessState::Running)
                        if monitor.ready_to_inject() =>
                    {
                        self.waiting_status.set_text("Injecting...");
                        match monitor.inject() {
                            Ok(()) => {
                                data.current_screen = AppScreen::Injected;
                                if let Some(ref game) = data.selected_game {
                                    self.injected_game_label.set_text(&format!(
                                        "{} (Seed: {})",
                                        game.display_name(),
                                        game.seed
                                    ));
                                }
                                self.show_screen(AppScreen::Injected);
                            }
                            Err(e) => {
                                self.waiting_status.set_text(&format!("Failed: {}", e));
                            }
                        }
                    }
                    (AppScreen::WaitingForGame, ProcessState::Running) => {
                        if let Some(remaining) = monitor.time_until_ready() {
                            self.waiting_status.set_text(&format!(
                                "Game detected! Injecting in {}s...",
                                remaining.as_secs() + 1
                            ));
                        }
                    }
                    (AppScreen::WaitingForGame, ProcessState::NotRunning) => {
                        self.waiting_status.set_text("Please launch the game");
                    }
                    (AppScreen::Injected, ProcessState::NotRunning) => {
                        monitor.reset();
                        data.current_screen = AppScreen::GameSelection;
                        self.show_screen(AppScreen::GameSelection);
                        data.load_games();
                    }
                    _ => {}
                }
            }
        }
    }

    fn show_screen(&self, screen: AppScreen) {
        // Token screen controls
        let show_token = screen == AppScreen::TokenInput;
        self.token_url_label.set_visible(show_token);
        self.token_url_input.set_visible(show_token);
        self.token_label.set_visible(show_token);
        self.token_input.set_visible(show_token);
        self.token_hint.set_visible(show_token);
        self.token_error.set_visible(show_token);
        self.token_connect_btn.set_visible(show_token);

        // Games screen controls
        let show_games = screen == AppScreen::GameSelection;
        self.games_user_label.set_visible(show_games);
        self.games_change_token_btn.set_visible(show_games);
        self.games_list_label.set_visible(show_games);
        self.games_list.set_visible(show_games);
        self.games_new_btn.set_visible(show_games);
        self.games_inject_btn.set_visible(show_games);
        self.games_status.set_visible(show_games);

        // Waiting screen controls
        let show_waiting = screen == AppScreen::WaitingForGame;
        self.waiting_title.set_visible(show_waiting);
        self.waiting_game_label.set_visible(show_waiting);
        self.waiting_status.set_visible(show_waiting);
        self.waiting_cancel_btn.set_visible(show_waiting);

        // Injected screen controls
        let show_injected = screen == AppScreen::Injected;
        self.injected_title.set_visible(show_injected);
        self.injected_game_label.set_visible(show_injected);
        self.injected_hint.set_visible(show_injected);
        self.injected_status.set_visible(show_injected);
        self.injected_back_btn.set_visible(show_injected);
    }

    // =========================================================================
    // Event Handlers
    // =========================================================================

    fn on_connect_click(&self) {
        let data_ref = self.data.borrow();
        let data = match data_ref.as_ref() {
            Some(d) => d,
            None => return,
        };

        let url = self.token_url_input.text();
        let token = self.token_input.text();

        if url.is_empty() || token.is_empty() {
            self.token_error.set_text("Please enter both URL and token");
            return;
        }

        self.token_error.set_text("");
        self.token_connect_btn.set_text("Connecting...");
        self.token_connect_btn.set_enabled(false);
        data.validate_token(url, token);
    }

    fn on_change_token_click(&self) {
        let mut data_ref = self.data.borrow_mut();
        let data = match data_ref.as_mut() {
            Some(d) => d,
            None => return,
        };

        data.config.mod_token = None;
        let _ = data.config.save();
        data.user = None;
        data.current_screen = AppScreen::TokenInput;

        self.token_input.set_text("");
        self.token_error.set_text("");
        self.token_connect_btn.set_text("Connect");
        self.token_connect_btn.set_enabled(true);
        self.show_screen(AppScreen::TokenInput);
    }

    fn on_game_selected(&self) {
        // Use try_borrow_mut to avoid panic if already borrowed (e.g., during clear())
        let Ok(mut data_ref) = self.data.try_borrow_mut() else {
            return;
        };
        let data = match data_ref.as_mut() {
            Some(d) => d,
            None => return,
        };

        if let Some(idx) = self.games_list.selected_item() {
            data.selected_game = data.games.get(idx).cloned();
        }
    }

    fn on_new_game_click(&self) {
        // Reset dialog state
        self.newgame_label_input.set_text("");
        self.newgame_folder_display.set_text("No folder selected");
        self.newgame_validation.set_text("");
        self.newgame_error.set_text("");
        self.newgame_create_btn.set_enabled(false);

        // Reset data
        let mut data_ref = self.data.borrow_mut();
        if let Some(data) = data_ref.as_mut() {
            data.rando_folder = None;
            data.rando_valid = false;
        }
        drop(data_ref);

        // Show dialog modally (disable main window)
        self.window.set_enabled(false);
        self.newgame_window.set_visible(true);
        self.newgame_window.set_focus();
    }

    fn on_newgame_dialog_close(&self) {
        self.close_newgame_dialog();
    }

    fn close_newgame_dialog(&self) {
        self.newgame_window.set_visible(false);
        self.window.set_enabled(true);
        self.window.set_focus();
    }

    fn on_inject_click(&self) {
        let mut data_ref = self.data.borrow_mut();
        let data = match data_ref.as_mut() {
            Some(d) => d,
            None => return,
        };

        if let Some(ref game) = data.selected_game {
            data.config.last_game_id = Some(game.id.clone());
            let _ = data.config.save();

            if let Some(ref mut monitor) = data.process_monitor {
                monitor.reset();
            }

            self.waiting_game_label.set_text(&format!(
                "{} (Seed: {})",
                game.display_name(),
                game.seed
            ));
            self.waiting_status.set_text("Please launch the game");
            data.current_screen = AppScreen::WaitingForGame;
            self.show_screen(AppScreen::WaitingForGame);
        }
    }

    fn on_browse_folder_click(&self) {
        let mut folder_dialog = nwg::FileDialog::default();

        if nwg::FileDialog::builder()
            .title("Select Randomizer Folder")
            .action(nwg::FileDialogAction::OpenDirectory)
            .build(&mut folder_dialog)
            .is_err()
        {
            return;
        }

        if folder_dialog.run(Some(&self.newgame_window)) {
            if let Ok(path_str) = folder_dialog.get_selected_item() {
                let path = PathBuf::from(path_str);
                let validation = validate_rando_folder(&path);

                let mut data_ref = self.data.borrow_mut();
                let data = match data_ref.as_mut() {
                    Some(d) => d,
                    None => return,
                };

                let folder_name = path
                    .file_name()
                    .map(|n| n.to_string_lossy().to_string())
                    .unwrap_or_else(|| path.display().to_string());
                self.newgame_folder_display.set_text(&folder_name);

                match validation {
                    Ok(validated) => {
                        let entity_count = match extract_rando_data(&validated) {
                            Ok(data) => data.entity_mapping.len(),
                            Err(_) => 0,
                        };
                        self.newgame_validation.set_text(&format!(
                            "Valid (Seed: {}, {} entity mappings)",
                            validated.header.seed, entity_count
                        ));
                        data.rando_folder = Some(validated);
                        data.rando_valid = true;
                        self.newgame_create_btn.set_enabled(true);
                    }
                    Err(e) => {
                        self.newgame_validation.set_text(&format!("Error: {}", e));
                        data.rando_folder = None;
                        data.rando_valid = false;
                        self.newgame_create_btn.set_enabled(false);
                    }
                }
            }
        }
    }

    fn on_newgame_cancel_click(&self) {
        self.close_newgame_dialog();
    }

    fn on_newgame_create_click(&self) {
        let data_ref = self.data.borrow();
        let data = match data_ref.as_ref() {
            Some(d) => d,
            None => return,
        };

        if !data.rando_valid {
            return;
        }

        if let Some(ref validated) = data.rando_folder {
            match extract_rando_data(validated) {
                Ok(rando_data) => {
                    let label = self.newgame_label_input.text();
                    let label_opt = if label.is_empty() { None } else { Some(label) };

                    self.newgame_create_btn.set_text("Creating...");
                    self.newgame_create_btn.set_enabled(false);
                    self.newgame_error.set_text("");
                    data.create_game(rando_data, label_opt);
                }
                Err(e) => {
                    self.newgame_error.set_text(&format!("Error: {}", e));
                }
            }
        }
    }

    fn on_waiting_cancel_click(&self) {
        let mut data_ref = self.data.borrow_mut();
        let data = match data_ref.as_mut() {
            Some(d) => d,
            None => return,
        };

        if let Some(ref mut monitor) = data.process_monitor {
            monitor.reset();
        }

        data.current_screen = AppScreen::GameSelection;
        self.show_screen(AppScreen::GameSelection);
    }

    fn on_injected_back_click(&self) {
        let mut data_ref = self.data.borrow_mut();
        let data = match data_ref.as_mut() {
            Some(d) => d,
            None => return,
        };

        if let Some(ref mut monitor) = data.process_monitor {
            monitor.reset();
        }

        data.current_screen = AppScreen::GameSelection;
        self.show_screen(AppScreen::GameSelection);
        data.load_games();
    }
}

// =============================================================================
// Public run function
// =============================================================================

pub fn run_app() {
    nwg::init().expect("Failed to init Native Windows GUI");

    // Set default font
    let mut font = nwg::Font::default();
    nwg::Font::builder()
        .family("Segoe UI")
        .size(17)
        .build(&mut font)
        .expect("Failed to build font");
    nwg::Font::set_global_default(Some(font));

    let app = LauncherApp::build_ui(Default::default()).expect("Failed to build UI");
    app.init();
    nwg::dispatch_thread_events();
}
