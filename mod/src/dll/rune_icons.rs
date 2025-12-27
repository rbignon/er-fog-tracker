//! Icon textures for the overlay
//!
//! Handles loading and managing:
//! - 14 rune icon textures (7 colored + 7 gray)
//! - 1 kindling icon texture

use hudhook::imgui::TextureId;
use hudhook::RenderContext;
use std::collections::HashMap;
use tracing::debug;

use crate::core::constants::GreatRune;

// =============================================================================
// EMBEDDED PNG BYTES
// =============================================================================

mod embedded {
    // Great Rune icons
    pub const GODRICK: &[u8] = include_bytes!("../../assets/runes/godrick.png");
    pub const GODRICK_GRAY: &[u8] = include_bytes!("../../assets/runes/godrick_gray.png");
    pub const RADAHN: &[u8] = include_bytes!("../../assets/runes/radahn.png");
    pub const RADAHN_GRAY: &[u8] = include_bytes!("../../assets/runes/radahn_gray.png");
    pub const MORGOTT: &[u8] = include_bytes!("../../assets/runes/morgott.png");
    pub const MORGOTT_GRAY: &[u8] = include_bytes!("../../assets/runes/morgott_gray.png");
    pub const RYKARD: &[u8] = include_bytes!("../../assets/runes/rykard.png");
    pub const RYKARD_GRAY: &[u8] = include_bytes!("../../assets/runes/rykard_gray.png");
    pub const MOHG: &[u8] = include_bytes!("../../assets/runes/mohg.png");
    pub const MOHG_GRAY: &[u8] = include_bytes!("../../assets/runes/mohg_gray.png");
    pub const MALENIA: &[u8] = include_bytes!("../../assets/runes/malenia.png");
    pub const MALENIA_GRAY: &[u8] = include_bytes!("../../assets/runes/malenia_gray.png");
    pub const UNBORN: &[u8] = include_bytes!("../../assets/runes/unborn.png");
    pub const UNBORN_GRAY: &[u8] = include_bytes!("../../assets/runes/unborn_gray.png");

    // Messmer's Kindling icon
    pub const KINDLING: &[u8] = include_bytes!("../../assets/messmers_kindling.png");

    // Death icon
    pub const DEATH: &[u8] = include_bytes!("../../assets/death.png");
}

// =============================================================================
// RUNE TEXTURES
// =============================================================================

/// Stores loaded texture IDs for all rune icons
pub struct RuneTextures {
    /// Colored textures (when rune is possessed)
    colored: HashMap<GreatRune, TextureId>,
    /// Gray textures (when rune is not possessed)
    gray: HashMap<GreatRune, TextureId>,
}

impl RuneTextures {
    /// Load all rune textures
    ///
    /// Call this in `ImguiRenderLoop::initialize()`.
    pub fn load(render_context: &mut dyn RenderContext) -> Result<Self, String> {
        let mut colored = HashMap::new();
        let mut gray = HashMap::new();

        let rune_data: [(GreatRune, &[u8], &[u8]); 7] = [
            (
                GreatRune::Godrick,
                embedded::GODRICK,
                embedded::GODRICK_GRAY,
            ),
            (GreatRune::Radahn, embedded::RADAHN, embedded::RADAHN_GRAY),
            (
                GreatRune::Morgott,
                embedded::MORGOTT,
                embedded::MORGOTT_GRAY,
            ),
            (GreatRune::Rykard, embedded::RYKARD, embedded::RYKARD_GRAY),
            (GreatRune::Mohg, embedded::MOHG, embedded::MOHG_GRAY),
            (
                GreatRune::Malenia,
                embedded::MALENIA,
                embedded::MALENIA_GRAY,
            ),
            (GreatRune::Unborn, embedded::UNBORN, embedded::UNBORN_GRAY),
        ];

        for (rune, color_png, gray_png) in rune_data {
            debug!(?rune, "Loading rune textures");

            let color_id = decode_and_load(render_context, color_png)
                .map_err(|e| format!("Failed to load {:?} colored: {}", rune, e))?;
            let gray_id = decode_and_load(render_context, gray_png)
                .map_err(|e| format!("Failed to load {:?} gray: {}", rune, e))?;

            colored.insert(rune, color_id);
            gray.insert(rune, gray_id);
        }

        Ok(Self { colored, gray })
    }

    /// Get texture ID for a rune based on possession state
    pub fn get_texture(&self, rune: GreatRune, possessed: bool) -> Option<TextureId> {
        if possessed {
            self.colored.get(&rune).copied()
        } else {
            self.gray.get(&rune).copied()
        }
    }

    /// Get all runes in display order
    pub fn runes_in_order() -> [GreatRune; 7] {
        [
            GreatRune::Godrick,
            GreatRune::Radahn,
            GreatRune::Morgott,
            GreatRune::Rykard,
            GreatRune::Mohg,
            GreatRune::Malenia,
            GreatRune::Unborn,
        ]
    }
}

// =============================================================================
// KINDLING TEXTURE
// =============================================================================

/// Stores the loaded texture ID for the Kindling icon
pub struct KindlingTexture {
    texture_id: TextureId,
}

impl KindlingTexture {
    /// Load the kindling texture
    ///
    /// Call this in `ImguiRenderLoop::initialize()`.
    pub fn load(render_context: &mut dyn RenderContext) -> Result<Self, String> {
        debug!("Loading kindling texture");

        let texture_id = decode_and_load(render_context, embedded::KINDLING)
            .map_err(|e| format!("Failed to load kindling: {}", e))?;

        Ok(Self { texture_id })
    }

    /// Get the texture ID
    pub fn texture_id(&self) -> TextureId {
        self.texture_id
    }
}

// =============================================================================
// DEATH TEXTURE
// =============================================================================

/// Stores the loaded texture ID for the Death icon
pub struct DeathTexture {
    texture_id: TextureId,
}

impl DeathTexture {
    /// Load the death texture
    ///
    /// Call this in `ImguiRenderLoop::initialize()`.
    pub fn load(render_context: &mut dyn RenderContext) -> Result<Self, String> {
        debug!("Loading death texture");

        let texture_id = decode_and_load(render_context, embedded::DEATH)
            .map_err(|e| format!("Failed to load death: {}", e))?;

        Ok(Self { texture_id })
    }

    /// Get the texture ID
    pub fn texture_id(&self) -> TextureId {
        self.texture_id
    }
}

// =============================================================================
// PNG DECODING
// =============================================================================

/// Decode PNG bytes to RGBA and load as texture
fn decode_and_load(
    render_context: &mut dyn RenderContext,
    png_bytes: &[u8],
) -> Result<TextureId, String> {
    use image::ImageReader;
    use std::io::Cursor;

    let img = ImageReader::new(Cursor::new(png_bytes))
        .with_guessed_format()
        .map_err(|e| format!("Failed to guess format: {}", e))?
        .decode()
        .map_err(|e| format!("Failed to decode PNG: {}", e))?;

    let rgba = img.to_rgba8();
    let (width, height) = rgba.dimensions();
    let raw_data = rgba.into_raw();

    debug!(width, height, bytes = raw_data.len(), "Decoded PNG");

    let texture_id = render_context
        .load_texture(&raw_data, width, height)
        .map_err(|e| format!("Failed to load texture: {:?}", e))?;

    Ok(texture_id)
}
