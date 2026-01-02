// Hotkey handling - keyboard shortcuts with modifier support

use serde::{Deserialize, Deserializer, Serialize, Serializer};
use std::cell::RefCell;
use std::collections::HashMap;
use windows::Win32::UI::Input::KeyboardAndMouse::GetAsyncKeyState;

// =============================================================================
// KEY STATE CACHE
// =============================================================================

// Thread-local cache for key states to avoid multiple GetAsyncKeyState calls
// for the same key in a single frame. This fixes the bug where multiple hotkeys
// with the same base key (e.g., "f9" and "ctrl+f9") would interfere with each other.
thread_local! {
    static KEY_STATE_CACHE: RefCell<KeyStateCache> = RefCell::new(KeyStateCache::new());
}

struct KeyStateCache {
    /// Maps key code to (is_just_pressed, is_held)
    states: HashMap<i32, (bool, bool)>,
    /// Frame counter to detect when cache should be invalidated
    frame: u64,
}

impl KeyStateCache {
    fn new() -> Self {
        Self {
            states: HashMap::new(),
            frame: 0,
        }
    }

    /// Start a new frame - this should be called once at the beginning of hotkey processing
    fn new_frame(&mut self) {
        self.frame += 1;
        self.states.clear();
    }

    /// Get the key state, caching the result for this frame
    fn get_key_state(&mut self, key_code: i32) -> (bool, bool) {
        *self.states.entry(key_code).or_insert_with(|| {
            let state = unsafe { GetAsyncKeyState(key_code) } as u16;
            let just_pressed = (state & 1) != 0;
            let is_held = (state & 0x8000) != 0;
            (just_pressed, is_held)
        })
    }
}

/// Call this once per frame before checking any hotkeys
pub fn begin_hotkey_frame() {
    KEY_STATE_CACHE.with(|cache| {
        cache.borrow_mut().new_frame();
    });
}

/// Get cached key state (just_pressed, is_held)
fn get_cached_key_state(key_code: i32) -> (bool, bool) {
    KEY_STATE_CACHE.with(|cache| cache.borrow_mut().get_key_state(key_code))
}

// =============================================================================
// KEY CODE MAPPING
// =============================================================================

/// All supported key names and their virtual key codes
const KEY_MAPPINGS: &[(&str, i32)] = &[
    // Letters (A-Z)
    ("a", 0x41),
    ("b", 0x42),
    ("c", 0x43),
    ("d", 0x44),
    ("e", 0x45),
    ("f", 0x46),
    ("g", 0x47),
    ("h", 0x48),
    ("i", 0x49),
    ("j", 0x4A),
    ("k", 0x4B),
    ("l", 0x4C),
    ("m", 0x4D),
    ("n", 0x4E),
    ("o", 0x4F),
    ("p", 0x50),
    ("q", 0x51),
    ("r", 0x52),
    ("s", 0x53),
    ("t", 0x54),
    ("u", 0x55),
    ("v", 0x56),
    ("w", 0x57),
    ("x", 0x58),
    ("y", 0x59),
    ("z", 0x5A),
    // Numbers (top row)
    ("0", 0x30),
    ("1", 0x31),
    ("2", 0x32),
    ("3", 0x33),
    ("4", 0x34),
    ("5", 0x35),
    ("6", 0x36),
    ("7", 0x37),
    ("8", 0x38),
    ("9", 0x39),
    // Function keys
    ("f1", 0x70),
    ("f2", 0x71),
    ("f3", 0x72),
    ("f4", 0x73),
    ("f5", 0x74),
    ("f6", 0x75),
    ("f7", 0x76),
    ("f8", 0x77),
    ("f9", 0x78),
    ("f10", 0x79),
    ("f11", 0x7A),
    ("f12", 0x7B),
    // Numpad
    ("numpad0", 0x60),
    ("numpad1", 0x61),
    ("numpad2", 0x62),
    ("numpad3", 0x63),
    ("numpad4", 0x64),
    ("numpad5", 0x65),
    ("numpad6", 0x66),
    ("numpad7", 0x67),
    ("numpad8", 0x68),
    ("numpad9", 0x69),
    ("num0", 0x60),
    ("num1", 0x61),
    ("num2", 0x62),
    ("num3", 0x63),
    ("num4", 0x64),
    ("num5", 0x65),
    ("num6", 0x66),
    ("num7", 0x67),
    ("num8", 0x68),
    ("num9", 0x69),
    ("multiply", 0x6A),
    ("add", 0x6B),
    ("subtract", 0x6D),
    ("decimal", 0x6E),
    ("divide", 0x6F),
    ("numpad_multiply", 0x6A),
    ("numpad_add", 0x6B),
    ("numpad_subtract", 0x6D),
    ("numpad_decimal", 0x6E),
    ("numpad_divide", 0x6F),
    // Navigation
    ("insert", 0x2D),
    ("ins", 0x2D),
    ("delete", 0x2E),
    ("del", 0x2E),
    ("suppr", 0x2E),
    ("home", 0x24),
    ("end", 0x23),
    ("pageup", 0x21),
    ("pagedown", 0x22),
    ("pgup", 0x21),
    ("pgdn", 0x22),
    ("up", 0x26),
    ("down", 0x28),
    ("left", 0x25),
    ("right", 0x27),
    // Special keys
    ("escape", 0x1B),
    ("esc", 0x1B),
    ("enter", 0x0D),
    ("return", 0x0D),
    ("space", 0x20),
    ("spacebar", 0x20),
    ("tab", 0x09),
    ("backspace", 0x08),
    ("back", 0x08),
    ("capslock", 0x14),
    ("caps", 0x14),
    ("numlock", 0x90),
    ("scrolllock", 0x91),
    ("printscreen", 0x2C),
    ("print", 0x2C),
    ("pause", 0x13),
    ("break", 0x13),
    // Punctuation & symbols
    ("semicolon", 0xBA),
    (";", 0xBA),
    ("equals", 0xBB),
    ("=", 0xBB),
    ("plus", 0xBB),
    ("comma", 0xBC),
    (",", 0xBC),
    ("minus", 0xBD),
    ("-", 0xBD),
    ("period", 0xBE),
    (".", 0xBE),
    ("slash", 0xBF),
    ("/", 0xBF),
    ("backtick", 0xC0),
    ("`", 0xC0),
    ("grave", 0xC0),
    ("openbracket", 0xDB),
    ("[", 0xDB),
    ("backslash", 0xDC),
    ("\\", 0xDC),
    ("closebracket", 0xDD),
    ("]", 0xDD),
    ("quote", 0xDE),
    ("'", 0xDE),
];

/// Convert key name to virtual key code
fn name_to_keycode(name: &str) -> Option<i32> {
    let name_lower = name.to_lowercase();
    KEY_MAPPINGS
        .iter()
        .find(|(n, _)| *n == name_lower)
        .map(|(_, code)| *code)
}

/// Convert virtual key code to key name (canonical name)
fn keycode_to_name(code: i32) -> &'static str {
    match code {
        0x41 => "A",
        0x42 => "B",
        0x43 => "C",
        0x44 => "D",
        0x45 => "E",
        0x46 => "F",
        0x47 => "G",
        0x48 => "H",
        0x49 => "I",
        0x4A => "J",
        0x4B => "K",
        0x4C => "L",
        0x4D => "M",
        0x4E => "N",
        0x4F => "O",
        0x50 => "P",
        0x51 => "Q",
        0x52 => "R",
        0x53 => "S",
        0x54 => "T",
        0x55 => "U",
        0x56 => "V",
        0x57 => "W",
        0x58 => "X",
        0x59 => "Y",
        0x5A => "Z",
        0x30 => "0",
        0x31 => "1",
        0x32 => "2",
        0x33 => "3",
        0x34 => "4",
        0x35 => "5",
        0x36 => "6",
        0x37 => "7",
        0x38 => "8",
        0x39 => "9",
        0x70 => "F1",
        0x71 => "F2",
        0x72 => "F3",
        0x73 => "F4",
        0x74 => "F5",
        0x75 => "F6",
        0x76 => "F7",
        0x77 => "F8",
        0x78 => "F9",
        0x79 => "F10",
        0x7A => "F11",
        0x7B => "F12",
        0x60 => "Numpad0",
        0x61 => "Numpad1",
        0x62 => "Numpad2",
        0x63 => "Numpad3",
        0x64 => "Numpad4",
        0x65 => "Numpad5",
        0x66 => "Numpad6",
        0x67 => "Numpad7",
        0x68 => "Numpad8",
        0x69 => "Numpad9",
        0x6A => "Multiply",
        0x6B => "Add",
        0x6D => "Subtract",
        0x6E => "Decimal",
        0x6F => "Divide",
        0x2D => "Insert",
        0x2E => "Delete",
        0x24 => "Home",
        0x23 => "End",
        0x21 => "PageUp",
        0x22 => "PageDown",
        0x26 => "Up",
        0x28 => "Down",
        0x25 => "Left",
        0x27 => "Right",
        0x1B => "Escape",
        0x0D => "Enter",
        0x20 => "Space",
        0x09 => "Tab",
        0x08 => "Backspace",
        0x14 => "CapsLock",
        0x90 => "NumLock",
        0x91 => "ScrollLock",
        0x2C => "PrintScreen",
        0x13 => "Pause",
        0xBA => ";",
        0xBB => "=",
        0xBC => ",",
        0xBD => "-",
        0xBE => ".",
        0xBF => "/",
        0xC0 => "`",
        0xDB => "[",
        0xDC => "\\",
        0xDD => "]",
        0xDE => "'",
        _ => "Unknown",
    }
}

// =============================================================================
// MODIFIER KEYS
// =============================================================================

/// Modifier key flags
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Modifiers {
    pub ctrl: bool,
    pub shift: bool,
    pub alt: bool,
}

impl Modifiers {
    const VK_CONTROL: i32 = 0x11;
    const VK_SHIFT: i32 = 0x10;
    const VK_MENU: i32 = 0x12; // Alt key

    /// Check if the required modifiers are currently held down (using cached state)
    pub fn are_held(&self) -> bool {
        let ctrl_ok = !self.ctrl || Self::is_key_held(Self::VK_CONTROL);
        let shift_ok = !self.shift || Self::is_key_held(Self::VK_SHIFT);
        let alt_ok = !self.alt || Self::is_key_held(Self::VK_MENU);
        ctrl_ok && shift_ok && alt_ok
    }

    fn is_key_held(key_code: i32) -> bool {
        get_cached_key_state(key_code).1
    }

    fn display_prefix(&self) -> String {
        let mut parts = Vec::new();
        if self.ctrl {
            parts.push("Ctrl");
        }
        if self.shift {
            parts.push("Shift");
        }
        if self.alt {
            parts.push("Alt");
        }
        if parts.is_empty() {
            String::new()
        } else {
            format!("{}+", parts.join("+"))
        }
    }
}

// =============================================================================
// HOTKEY TYPE
// =============================================================================

/// A hotkey with optional modifiers (Ctrl, Shift, Alt) and a main key
#[derive(Debug, Clone, Copy)]
pub struct Hotkey {
    pub key: i32,
    pub modifiers: Modifiers,
}

impl Hotkey {
    /// Create a hotkey from a key name (e.g., "f9", "a", "numpad0")
    /// Returns None if the key name is not recognized
    pub fn from_name(name: &str) -> Option<Self> {
        name_to_keycode(name).map(|key| Hotkey {
            key,
            modifiers: Modifiers::default(),
        })
    }

    /// Get the display name for this hotkey
    pub fn name(&self) -> String {
        format!(
            "{}{}",
            self.modifiers.display_prefix(),
            keycode_to_name(self.key)
        )
    }

    /// Check if this hotkey was just pressed (key edge + modifiers held)
    /// Uses cached key state to avoid consuming the "just pressed" bit multiple times
    pub fn is_just_pressed(&self) -> bool {
        let (just_pressed, _) = get_cached_key_state(self.key);
        just_pressed && self.modifiers.are_held()
    }
}

/// Parse a hotkey string like "ctrl+shift+f9" or "f9"
fn parse_hotkey(s: &str) -> Result<Hotkey, String> {
    let parts: Vec<&str> = s.split('+').map(|p| p.trim()).collect();

    if parts.is_empty() {
        return Err("Empty hotkey string".to_string());
    }

    let mut modifiers = Modifiers::default();
    let mut main_key: Option<i32> = None;

    for part in parts {
        let part_lower = part.to_lowercase();
        match part_lower.as_str() {
            "ctrl" | "control" => modifiers.ctrl = true,
            "shift" => modifiers.shift = true,
            "alt" => modifiers.alt = true,
            _ => {
                if main_key.is_some() {
                    return Err(format!(
                        "Multiple main keys specified: already have one, found '{}'",
                        part
                    ));
                }
                main_key = Some(name_to_keycode(part).ok_or_else(|| {
                    format!(
                        "Unknown key name: '{}'. See config file for valid key names.",
                        part
                    )
                })?);
            }
        }
    }

    let key = main_key.ok_or_else(|| "No main key specified in hotkey".to_string())?;

    Ok(Hotkey { key, modifiers })
}

impl Serialize for Hotkey {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut parts = Vec::new();
        if self.modifiers.ctrl {
            parts.push("ctrl".to_string());
        }
        if self.modifiers.shift {
            parts.push("shift".to_string());
        }
        if self.modifiers.alt {
            parts.push("alt".to_string());
        }
        parts.push(keycode_to_name(self.key).to_lowercase());
        serializer.serialize_str(&parts.join("+"))
    }
}

impl<'de> Deserialize<'de> for Hotkey {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let s = String::deserialize(deserializer)?;
        parse_hotkey(&s).map_err(serde::de::Error::custom)
    }
}
