//! EMEVD parsing for extracting fog gate entity mappings.
//!
//! This module parses Elden Ring EMEVD files (event scripts) to extract
//! fog gate destination entity IDs. FogMod uses entity IDs in the 755890xxx
//! range for its spawn points.

use byteorder::{BigEndian, LittleEndian, ReadBytesExt};
use flate2::read::ZlibDecoder;
use std::collections::HashMap;
use std::io::{Cursor, Read, Seek, SeekFrom};
use thiserror::Error;

// =============================================================================
// Error Types
// =============================================================================

#[derive(Error, Debug)]
pub enum EmevdError {
    #[error("Invalid DCX magic")]
    InvalidDcxMagic,

    #[error("Unsupported DCX format: {0}")]
    UnsupportedDcxFormat(String),

    #[error("Invalid EMEVD magic")]
    InvalidEmevdMagic,

    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    #[error("Decompression failed: {0}")]
    DecompressFailed(String),
}

// =============================================================================
// DCX Decompression
// =============================================================================

/// Decompress a DCX file (DFLT/zlib compression only)
fn decompress_dcx(data: &[u8]) -> Result<Vec<u8>, EmevdError> {
    if data.len() < 0x50 {
        return Err(EmevdError::InvalidDcxMagic);
    }

    let mut cursor = Cursor::new(data);

    // Read magic "DCX\0"
    let mut magic = [0u8; 4];
    cursor.read_exact(&mut magic)?;

    if &magic != b"DCX\0" {
        return Err(EmevdError::InvalidDcxMagic);
    }

    // Skip unk04
    cursor.read_u32::<BigEndian>()?;

    // Read offsets
    let _dcs_offset = cursor.read_u32::<BigEndian>()?;
    let dcp_offset = cursor.read_u32::<BigEndian>()?;

    // Read DCS header for uncompressed size
    cursor.set_position(0x18);
    let mut dcs_magic = [0u8; 4];
    cursor.read_exact(&mut dcs_magic)?;

    if &dcs_magic != b"DCS\0" {
        return Err(EmevdError::UnsupportedDcxFormat(
            "Missing DCS header".to_string(),
        ));
    }

    let uncompressed_size = cursor.read_u32::<BigEndian>()? as usize;

    // Read DCP header for compression type
    cursor.set_position(dcp_offset as u64);
    let mut dcp_magic = [0u8; 4];
    cursor.read_exact(&mut dcp_magic)?;

    if &dcp_magic != b"DCP\0" {
        return Err(EmevdError::UnsupportedDcxFormat(
            "Missing DCP header".to_string(),
        ));
    }

    let mut compression = [0u8; 4];
    cursor.read_exact(&mut compression)?;

    if &compression != b"DFLT" {
        return Err(EmevdError::UnsupportedDcxFormat(format!(
            "Compression type {:?} not supported",
            String::from_utf8_lossy(&compression)
        )));
    }

    // Read DCP header size
    let dcp_header_size = cursor.read_u32::<BigEndian>()? as usize;

    // DCA follows DCP
    let dca_offset = dcp_offset as usize + dcp_header_size;
    cursor.set_position(dca_offset as u64);

    let mut dca_magic = [0u8; 4];
    cursor.read_exact(&mut dca_magic)?;

    if &dca_magic != b"DCA\0" {
        return Err(EmevdError::UnsupportedDcxFormat(
            "Missing DCA header".to_string(),
        ));
    }

    let dca_header_size = cursor.read_u32::<BigEndian>()? as usize;

    // Compressed data starts after DCA header
    let data_offset = dca_offset + dca_header_size;
    let compressed = &data[data_offset..];

    // Decompress with zlib
    let mut decoder = ZlibDecoder::new(compressed);
    let mut decompressed = Vec::with_capacity(uncompressed_size);
    decoder
        .read_to_end(&mut decompressed)
        .map_err(|e| EmevdError::DecompressFailed(e.to_string()))?;

    Ok(decompressed)
}

// =============================================================================
// EMEVD Parsing
// =============================================================================

/// A fog warp extracted from EMEVD
#[derive(Debug, Clone)]
pub struct FogWarp {
    pub source_entity: Option<u32>,
    pub dest_entity: u32,
    pub dest_map: String,
}

/// Parse an EMEVD file and extract fog warps
pub fn parse_emevd(data: &[u8]) -> Result<Vec<FogWarp>, EmevdError> {
    let mut cursor = Cursor::new(data);

    // Read magic "EVD\0"
    let mut magic = [0u8; 4];
    cursor.read_exact(&mut magic)?;

    if &magic != b"EVD\0" {
        return Err(EmevdError::InvalidEmevdMagic);
    }

    // Read flags
    let _big_endian = cursor.read_u8()? != 0;
    let is_64bit = cursor.read_u8()? == 0xFF;

    // Skip remaining flags
    cursor.read_u8()?;
    cursor.read_u8()?;

    // Skip version and file_size
    cursor.read_u32::<LittleEndian>()?;
    cursor.read_u32::<LittleEndian>()?;

    // Helper to read varint
    let read_varint = |cursor: &mut Cursor<&[u8]>| -> std::io::Result<u64> {
        if is_64bit {
            cursor.read_u64::<LittleEndian>()
        } else {
            Ok(cursor.read_u32::<LittleEndian>()? as u64)
        }
    };

    // Read offset table
    let events_count = read_varint(&mut cursor)?;
    let events_offset = read_varint(&mut cursor)?;
    let instructions_count = read_varint(&mut cursor)?;
    let instructions_offset = read_varint(&mut cursor)?;

    // Skip to base_arg_data_offset (position 0x78 for 64-bit)
    if is_64bit {
        cursor.set_position(0x78);
    } else {
        cursor.set_position(0x38);
    }
    let base_arg_data_offset = read_varint(&mut cursor)?;

    // Instruction header size
    let instr_header_size: u64 = if is_64bit { 32 } else { 20 };
    let invalid_offset: u64 = if is_64bit {
        0xFFFFFFFFFFFFFFFF
    } else {
        0xFFFFFFFF
    };

    // Read all instructions
    #[derive(Debug)]
    struct Instruction {
        category: u32,
        index: u32,
        args: Vec<u32>,
    }

    let mut instructions = Vec::with_capacity(instructions_count as usize);
    cursor.set_position(instructions_offset);

    for _ in 0..instructions_count {
        let category = cursor.read_u32::<LittleEndian>()?;
        let index = cursor.read_u32::<LittleEndian>()?;
        let args_size = read_varint(&mut cursor)?;
        let args_offset = read_varint(&mut cursor)?;

        // Skip event_layers and padding
        cursor.read_i32::<LittleEndian>()?;
        cursor.read_u32::<LittleEndian>()?;

        // Read arguments
        let mut args = Vec::new();
        if args_size > 0 && args_offset != invalid_offset {
            let arg_start = base_arg_data_offset + args_offset;
            let current_pos = cursor.position();

            if arg_start + args_size <= data.len() as u64 {
                cursor.set_position(arg_start);
                let num_args = (args_size / 4) as usize;
                for _ in 0..num_args {
                    args.push(cursor.read_u32::<LittleEndian>()?);
                }
                cursor.set_position(current_pos);
            }
        }

        instructions.push(Instruction {
            category,
            index,
            args,
        });
    }

    // Event header size
    let event_header_size: u64 = if is_64bit { 48 } else { 28 };

    // Read events and extract fog warps
    const FOGMOD_ENTITY_MIN: u32 = 755890000;
    const FOGMOD_ENTITY_MAX: u32 = 755899999;

    let mut warps = Vec::new();
    cursor.set_position(events_offset);

    for _ in 0..events_count {
        let _event_id = cursor.read_i64::<LittleEndian>()?;
        let num_instructions = read_varint(&mut cursor)?;
        let instructions_offset_bytes = read_varint(&mut cursor)?;

        // Skip remaining event header fields
        read_varint(&mut cursor)?; // num_parameters
        read_varint(&mut cursor)?; // parameters_offset
        cursor.read_u32::<LittleEndian>()?; // restart_behavior
        cursor.read_u32::<LittleEndian>()?; // padding

        // Calculate instruction range for this event
        let instr_index = (instructions_offset_bytes / instr_header_size) as usize;
        let instr_end = instr_index + num_instructions as usize;

        if instr_end > instructions.len() {
            continue;
        }

        let event_instrs = &instructions[instr_index..instr_end];

        // Find Warp Player instruction (category=2003, index=14) with FogMod destination
        let warp_instr = event_instrs.iter().find(|i| {
            i.category == 2003
                && i.index == 14
                && i.args.len() >= 2
                && i.args[1] >= FOGMOD_ENTITY_MIN
                && i.args[1] <= FOGMOD_ENTITY_MAX
        });

        if let Some(warp) = warp_instr {
            let dest_map_type = warp.args[0];
            let dest_entity = warp.args[1];

            // Find source entity from Rotate Character (2004:14)
            let source_entity = event_instrs.iter().find_map(|i| {
                if i.category == 2004
                    && i.index == 14
                    && i.args.len() >= 2
                    && i.args[1] >= FOGMOD_ENTITY_MIN
                    && i.args[1] <= FOGMOD_ENTITY_MAX
                {
                    Some(i.args[1])
                } else {
                    None
                }
            });

            // Decode map type to map ID
            let dest_map = decode_map_type(dest_map_type);

            warps.push(FogWarp {
                source_entity,
                dest_entity,
                dest_map,
            });
        }
    }

    Ok(warps)
}

/// Decode map type to map ID string (e.g., 2080 -> m32_08_00_00)
fn decode_map_type(map_type: u32) -> String {
    let aa = map_type & 0xFF;
    let bb = (map_type >> 8) & 0xFF;

    if aa == 60 {
        let cc = (map_type >> 16) & 0xFF;
        format!("m60_{:02}_{:02}_00", bb, cc)
    } else {
        format!("m{:02}_{:02}_00_00", aa, bb)
    }
}

// =============================================================================
// Public API
// =============================================================================

/// Entity mapping: dest_entity -> (source_map, dest_map, source_entity)
pub type EntityMapping = HashMap<u32, EntityInfo>;

#[derive(Debug, Clone, serde::Serialize)]
pub struct EntityInfo {
    pub source_map: String,
    pub dest_map: String,
    pub source_entity: Option<u32>,
}

/// Parse all EMEVD files in a directory and build entity mapping
pub fn build_entity_mapping(event_dir: &std::path::Path) -> Result<EntityMapping, EmevdError> {
    let mut mapping = EntityMapping::new();

    let entries = std::fs::read_dir(event_dir).map_err(|e| EmevdError::Io(e))?;

    for entry in entries.flatten() {
        let path = entry.path();

        // Only process .emevd.dcx files
        let filename = path.file_name().and_then(|n| n.to_str()).unwrap_or("");
        if !filename.ends_with(".emevd.dcx") {
            continue;
        }

        // Skip common files
        if filename == "common.emevd.dcx" || filename == "common_func.emevd.dcx" {
            continue;
        }

        // Extract source map name
        let source_map = filename.replace(".emevd.dcx", "");

        // Read and decompress
        let dcx_data = match std::fs::read(&path) {
            Ok(data) => data,
            Err(_) => continue,
        };

        let emevd_data = match decompress_dcx(&dcx_data) {
            Ok(data) => data,
            Err(_) => continue,
        };

        // Parse EMEVD
        let warps = match parse_emevd(&emevd_data) {
            Ok(w) => w,
            Err(_) => continue,
        };

        // Add to mapping
        for warp in warps {
            mapping.insert(
                warp.dest_entity,
                EntityInfo {
                    source_map: source_map.clone(),
                    dest_map: warp.dest_map,
                    source_entity: warp.source_entity,
                },
            );
        }
    }

    Ok(mapping)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_decode_map_type() {
        // m32_08 = 32 + (8 << 8) = 32 + 2048 = 2080
        assert_eq!(decode_map_type(2080), "m32_08_00_00");

        // m11_05 = 11 + (5 << 8) = 11 + 1280 = 1291
        assert_eq!(decode_map_type(1291), "m11_05_00_00");
    }
}
