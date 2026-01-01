//! Animation IDs and names
//!
//! Exhaustive list of known Elden Ring animations, compiled from:
//! - Cheat Engine table (eldenring_all-in-one_Hexinton-v5.0_ce7.5.ct)
//! - Manual discovery during mod development
//!
//! The Debug trait is used for human-readable labels in logs.

use num_enum::TryFromPrimitive;

/// Known animation IDs in Elden Ring
///
/// Use `Animation::try_from(id)` to convert a raw ID, then `format!("{:?}", anim)`
/// for a human-readable name.
#[repr(u32)]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, TryFromPrimitive)]
pub enum Animation {
    // =========================================================================
    // Movement / Combat (6xxx)
    // =========================================================================
    HunchedOverWrithingStart = 6000,
    HunchedOverWrithing = 6001,
    RunForwardSlash = 6002,

    // =========================================================================
    // Abductor Virgin grab (15xxx)
    // =========================================================================
    /// Abductor Virgin grab teleport (Raya Lucaria → Volcano Manor)
    AbductorVirginGrab = 15004000,

    // =========================================================================
    // Death / Status (17xxx, 18xxx)
    // =========================================================================
    DieFromPoison = 17140,
    Nothing18140 = 18140,

    // =========================================================================
    // Turns / Kicks (26xxx)
    // =========================================================================
    Turn90Left = 26001,
    Turn90Right = 26011,
    SmallKick26020 = 26020,
    Turn180_26021 = 26021,
    SmallKick26030 = 26030,
    Turn180_26031 = 26031,

    // =========================================================================
    // Item Use (50xxx)
    // =========================================================================
    CantUseItem = 50050,
    /// Memory of Grace item use
    ItemUseMemory = 50230,
    KneelDownDreamMist = 50250,
    /// Pureblood Knight's Medal teleport
    Medal = 50340,

    // =========================================================================
    // Interactions - Doors, Objects (60xxx)
    // =========================================================================
    PushSmallDoor = 60000,
    PullSmallDoor60001 = 60001,
    PullSmallDoor60002 = 60002,
    PushSmallDoor60003 = 60003,
    /// Horned Remains teleport (hold hand up to door)
    HornedRemains = 60010,
    MoveLeverPushMediumDoor = 60020,
    PushHeavyDoor60030 = 60030,
    PushVeryHeavyDoor60040 = 60040,
    /// Fog wall traversal
    FogWall = 60060,
    PickupItem60070 = 60070,
    PickupItem60071 = 60071,
    OpenChest60080 = 60080,
    BendOverPickupItem = 60090,
    Prayer60100 = 60100,
    PushHeadHeight = 60110,
    PushWaistHeight = 60120,
    DisappearReappear = 60130,
    StandUpFogNoise = 60131,
    PushHeavyDoor60160 = 60160,
    PushVeryHeavyDoor60170 = 60170,
    PushBiggerVeryHeavyDoor60180 = 60180,
    PushBiggerVeryHeavyDoor60190 = 60190,
    PullLever = 60200,
    TwistLever = 60201,
    PushIntoGround = 60202,
    LadderKick = 60210,
    Stuck60220 = 60220,
    PushLargeRotatingLever60230 = 60230,
    PushLargeRotatingLever60231 = 60231,
    HoldHandToHead = 60240,
    Stuck60241 = 60241,
    WarpNoEffect = 60250,
    InstantlyInvis = 60260,
    TPoseError = 60265,
    HoldUp3Fingers = 60270,
    Stuck60350 = 60350,
    Stuck60360 = 60360,
    OpenChest60370 = 60370,
    PlaceFistOnSurface = 60380,
    Stuck60390 = 60390,
    LiftGate = 60400,
    TouchGroundBlueFire = 60450,
    StandUpFromBlueFire = 60451,
    TPoseSplitSecond = 60455,
    StandUpFromGround = 60456,
    /// "Back to entrance" teleport
    BackToEntrance = 60460,
    /// Sending gate (blue) - enter
    SendingGateBlue = 60470,
    /// Sending gate (blue) - exit
    SendingGateBlueExit = 60471,
    /// Sending gate (red) - enter
    SendingGateRed = 60472,
    /// Sending gate (red) - exit
    SendingGateRedExit = 60473,
    LookThroughMonocular = 60480,
    LookingThroughMonocular = 60481,
    StopLookingThroughMonocular = 60482,
    /// Waygate teleport (hand turns blue)
    Waygate = 60490,
    InvisFlashRiseMetallic = 60500,
    AppearFromAirParticles = 60501,
    AppearStandingPinkParticles = 60502,
    Tpose60503 = 60503,
    Tpose60504 = 60504,
    DisappearStandingPinkParticles = 60505,
    HoldUpPalmToSky = 60510,
    RetractPalmToSky60511 = 60511,
    RetractPalmToSky60512 = 60512,
    RetractPalmEatFromHand = 60513,
    ShatterOrangeGlass60520 = 60520,
    ShatterOrangeGlass60521 = 60521,
    ShatterYellowGlass = 60522,
    ShatterOrangeWhiteGlass = 60523,
    ShatterRedGlass = 60524,
    ShatterGoldGlass = 60525,
    PullFromGround = 60530,
    PutHandsAtSide60540 = 60540,
    PutHandsAtSide60541 = 60541,
    PutHandsAtSide60542 = 60542,
    EmitOrangeParticles = 60543,
    HoldOutHand60550 = 60550,
    KneelDownThenStand = 60560,
    PullFromWall60750 = 60750,
    StepUpPullFromSurface = 60760,
    PullFromWall60780 = 60780,
    OverhandPullFromWall = 60790,
    Prayer60800 = 60800,
    PlaceSomethingStoneNoise60810 = 60810,
    PlaceSomethingStoneNoise60811 = 60811,

    // =========================================================================
    // Spawn / Summon (63xxx)
    // =========================================================================
    /// Player spawn animation
    Spawn = 63000,
    StandUpFromInvis = 63010,
    StandUpSlowFistPump = 63020,
    WhiteSummonAnimation = 63021,
    AppearWhileStanding = 63040,
    Nothing63050 = 63050,
    CrouchedThenStandSlowly = 63060,
    StandUpFingerPointingSky = 63061,
    StandUpHoldingFist = 63070,
    Nudge63080 = 63080,
    AppearInvisFistOnChest = 63090,

    // =========================================================================
    // Unknown (65xxx)
    // =========================================================================
    Nothing65012 = 65012,
    Nothing65013 = 65013,
    Nothing65030 = 65030,
    UseEffigy = 65040,

    // =========================================================================
    // Death / Lie Down (67xxx)
    // =========================================================================
    DieFromPoisonNoKill = 67000,
    StandUp67001 = 67001,
    /// Placidusax arena access (lie down)
    PlacidusaxLieDown = 67010,
    LieDownFlat67011 = 67011,
    StandUpSlow67020 = 67020,
    Nothing67030 = 67030,
    Nothing67040 = 67040,
    Nothing67050 = 67050,
    Nothing67060 = 67060,
    GrabFaceWretchCollapse = 67070,
    HoldOutHandLoudWhoosh = 67080,
    StandUp67090 = 67090,
    CrouchingHandOutThenStand = 67100,

    // =========================================================================
    // Grace / Conversation (68xxx)
    // =========================================================================
    LostGraceDiscovered68000 = 68000,
    LostGraceDiscovered68001 = 68001,
    LostGraceDiscoveredThenSit = 68002,
    SitAtGrace68010 = 68010,
    SitAtGrace68011 = 68011,
    StandUpFromGrace68012 = 68012,
    SitAtGraceCrossedLegs68020 = 68020,
    SitAtGraceCrossedLegs68021 = 68021,
    StandUpFromGrace68022 = 68022,
    SitAtGraceCasual = 68023,
    SitAtGraceLookToSide = 68024,
    ConversationLookUp68040 = 68040,
    ConversationLookUp68041 = 68041,
    ConversationEnd = 68042,
    Stuck68043 = 68043,
    MoveBackwardsSlightly = 68050,
    HoldOutArmsWarp = 68100,
    HoldOutArmsWarpReappear = 68101,
    /// Erdtree burn cutscene (Melina sacrifice)
    ErdtreeBurn = 68110,
    Nothing68120 = 68120,
    SitAtGraceLevelUp68200 = 68200,
    StopLevelingUp68201 = 68201,
    StopLevelingUp68202 = 68202,
    SitAtGraceLevelUpStop = 68205,
    StopLevelingUp68206 = 68206,
    StopLevelingUp68207 = 68207,
    StopGivingAttention68210 = 68210,
    StopGivingAttention68211 = 68211,
    StopGivingAttention68212 = 68212,
    StopGivingAttention68215 = 68215,
    StopGivingAttention68216 = 68216,
    StopGivingAttention68217 = 68217,
    StopGivingAttention68220 = 68220,
    StopGivingAttention68221 = 68221,
    StopGivingAttention68222 = 68222,
    StopGivingAttention68225 = 68225,
    StopGivingAttention68226 = 68226,
    StopGivingAttention68227 = 68227,

    // =========================================================================
    // Covenant / Offering (69xxx)
    // =========================================================================
    PlaceSomethingOnGround = 69000,
    HoldSomethingOnGround = 69001,
    KneelingHandOutThenStand = 69002,
    KneelOfferToCovenant = 69003,
    PrayerOfferSomething = 69010,
    Kneel69030 = 69030,

    // =========================================================================
    // Gestures (80xxx - 81xxx)
    // =========================================================================
    Bow = 80000,
    ProperBow = 80010,
    MyThanks = 80020,
    Curtsy = 80030,
    Gesture80040 = 80040,
    Gesture80050 = 80050,
    Gesture80051 = 80051,
    Gesture80060 = 80060,
    Gesture80070 = 80070,
    Gesture80080 = 80080,
    Gesture80090 = 80090,
    Gesture80100 = 80100,
    Gesture80131 = 80131,
    Gesture80200 = 80200,
    Gesture80210 = 80210,
    Gesture80220 = 80220,
    Gesture80230 = 80230,
    Gesture80240 = 80240,
    Gesture80250 = 80250,
    Gesture80300 = 80300,
    Gesture80400 = 80400,
    Gesture80410 = 80410,
    Gesture80500 = 80500,
    Gesture80510 = 80510,
    Gesture80520 = 80520,
    Gesture80530 = 80530,
    Gesture80540 = 80540,
    Gesture80541 = 80541,
    Gesture80550 = 80550,
    Gesture80600 = 80600,
    Gesture80700 = 80700,
    Gesture80710 = 80710,
    Gesture80720 = 80720,
    Gesture80730 = 80730,
    Gesture80800 = 80800,
    Gesture80801 = 80801,
    Gesture80900 = 80900,
    Gesture80901 = 80901,
    Gesture80910 = 80910,
    Gesture80911 = 80911,
    Gesture80920 = 80920,
    Gesture80921 = 80921,
    Gesture80930 = 80930,
    Gesture80931 = 80931,
    Gesture80940 = 80940,
    Gesture80941 = 80941,
    Gesture80950 = 80950,
    Gesture80951 = 80951,
    Gesture80960 = 80960,
    Gesture80961 = 80961,
    Gesture80970 = 80970,
    Gesture80971 = 80971,
    Gesture80980 = 80980,
    Gesture80981 = 80981,
    Gesture81000 = 81000,
    Gesture81001 = 81001,
    Gesture81010 = 81010,
    Gesture81011 = 81011,
    Gesture81020 = 81020,
    Gesture81021 = 81021,
    Gesture81030 = 81030,
    Gesture81031 = 81031,
    Gesture81040 = 81040,
    Gesture81041 = 81041,
    Gesture81050 = 81050,
    Gesture81051 = 81051,
    Gesture81060 = 81060,
    Gesture81061 = 81061,
    Gesture81080 = 81080,
    Gesture81081 = 81081,

    // =========================================================================
    // Misc / Cutscene (90xxx)
    // =========================================================================
    PlaceSomethingOnSurface = 90000,
    CompletelyStuck90001 = 90001,
    CompletelyStuck90002 = 90002,
    CompletelyStuck90003 = 90003,
    LayingFaceFirstOnGround = 90004,
    EdgySlowWalkFromInvis = 90005,
    WalkForwardLoop = 90006,
    Invis90007 = 90007,
    SpiritSummonCube = 90008,
    DeathNoKill = 90009,
    HandsTogetherStomach = 90100,
    Stuck90101 = 90101,
    Stuck90102 = 90102,
    Stuck90103 = 90103,
    Stuck90104 = 90104,
    Stuck90105 = 90105,
    Stuck90106 = 90106,
    Stuck90107 = 90107,
    Stuck90108 = 90108,
    Stuck90109 = 90109,
    Stuck90200 = 90200,
    ReachHandOutHot = 90201,
    ReachHandOutMadness = 90202,
    RestHandLowHum = 90203,
    KneelPullSoul = 90204,
    KneelDownHug90205 = 90205,
    KneelDownHug90206 = 90206,
    BeingHeld90207 = 90207,
    PrayerHandsWhiteCircle = 90208,
    Stuck90209 = 90209,
    SitSlowlyBurn = 90210,
    SitSlowlyBurnNoFire = 90211,
    KneelDownHug90300 = 90300,
    BeingHeld90301 = 90301,
    GetUpFromHeld90302 = 90302,
    KneelDownHug90305 = 90305,
    BeingHeld90306 = 90306,
    GetUpFromHeld90307 = 90307,
    Nudge90310 = 90310,
    TPoseFreeze = 90311,
    Nothing90312 = 90312,
    CrouchedLookingUp = 90315,
    CrouchedLookingUpLoop = 90316,
    EatGrass = 90317,
    Nothing90320 = 90320,
    Nothing90321 = 90321,
    Nothing90322 = 90322,
    Nothing90325 = 90325,
    Nothing90326 = 90326,
    Nothing90327 = 90327,
    SittingForASecond = 90330,
    SittingLookingUp = 90331,
    SittingLookingDown = 90332,
    KneelDownHug90335 = 90335,
    BeingHeld90336 = 90336,
    GetUpFromHeld90337 = 90337,
    HandsTogetherPainThrowBack = 90400,
    HandsBoundPain = 90401,
    HandUnderChinPain = 90402,
    OnGroundPain = 90403,

    // =========================================================================
    // End markers (99xxx)
    // =========================================================================
    Nothing99998 = 99998,
    Nothing99999 = 99999,

    // =========================================================================
    // Special / High IDs
    // =========================================================================
    CrouchSplitSecond150250 = 150250,
    CrouchSplitSecond160070 = 160070,
    PickupItemCrouched = 360070,
    InvisForSeconds = 6026000,

    // =========================================================================
    // Custom discoveries (not in CE table)
    // =========================================================================
    /// Liurnia Divine Tower door teleport
    LiurniaTowerDoor = 12202126,
    /// Post-boss warp animation
    PostBossWarp = 12020210,
    /// Lake of Rot coffin warp
    CoffinLakeOfRot = 2020210,
    /// Deeproot Depths coffin warp
    CoffinDeeproot = 2029050,
    /// Divine Tower of Liurnia
    LiurniaDivineTower = 12020110,
    /// Way to Metyr
    WayToMetyr = 12000000,
    /// Burning Scaling Tree
    BurningScalingTree = 12022200,
}

impl Animation {
    /// Get the raw animation ID
    pub fn as_u32(self) -> u32 {
        self as u32
    }

    /// Check if this animation is a teleportation animation
    pub fn is_teleport(self) -> bool {
        matches!(
            self,
            Self::FogWall
                | Self::BackToEntrance
                | Self::Waygate
                | Self::SendingGateBlue
                | Self::SendingGateRed
                | Self::Medal
                | Self::HornedRemains
                | Self::LiurniaTowerDoor
                | Self::PostBossWarp
                | Self::ErdtreeBurn
                | Self::PlacidusaxLieDown
                | Self::AbductorVirginGrab
                | Self::CoffinLakeOfRot
                | Self::CoffinDeeproot
                | Self::LiurniaDivineTower
                | Self::BurningScalingTree // Note: WayToMetyr (12000000) removed - it's a false positive that triggers
                                           // during normal gameplay and incorrectly creates pending warps
        )
    }

    /// Check if this animation is a "real" fog gate or waygate transition.
    ///
    /// These are transitions that should be tracked even when target_grace is set,
    /// because waygate transitions can happen while a grace is targeted (the player
    /// uses a waygate instead of completing the fast travel).
    ///
    /// This is a subset of is_teleport() - only the actual fog/waygate animations.
    pub fn is_fog_or_waygate(self) -> bool {
        matches!(
            self,
            Self::FogWall | Self::Waygate | Self::SendingGateBlue | Self::SendingGateRed
        )
    }
}

/// Get a human-readable label for an animation ID
///
/// Returns the Debug name for known animations, "IDLE" for 0,
/// or the raw ID as string for unknown animations.
pub fn get_animation_label(anim_id: u32) -> String {
    match Animation::try_from(anim_id) {
        Ok(anim) => format!("{:?}", anim),
        Err(_) if anim_id == 0 => "IDLE".to_string(),
        Err(_) => format!("{}", anim_id),
    }
}

/// Get teleport type name from animation ID
///
/// Returns the name of the teleport animation (Debug format) if the animation ID
/// corresponds to a known teleportation animation, or None otherwise.
pub fn get_teleport_type(anim_id: u32) -> Option<String> {
    Animation::try_from(anim_id)
        .ok()
        .filter(|a| a.is_teleport())
        .map(|a| format!("{:?}", a))
}

/// Check if an animation ID is a teleportation animation
pub fn is_teleport_animation(anim_id: u32) -> bool {
    Animation::try_from(anim_id)
        .map(|a| a.is_teleport())
        .unwrap_or(false)
}

/// Check if an animation ID is a fog gate or waygate transition
///
/// These are animations that indicate a real fog/waygate traversal,
/// not just a Fast Travel or cutscene animation.
pub fn is_fog_or_waygate_animation(anim_id: u32) -> bool {
    Animation::try_from(anim_id)
        .map(|a| a.is_fog_or_waygate())
        .unwrap_or(false)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_teleport_animations() {
        assert!(Animation::FogWall.is_teleport());
        assert!(Animation::Waygate.is_teleport());
        assert!(Animation::SendingGateBlue.is_teleport());
        assert!(Animation::SendingGateRed.is_teleport());
        assert!(Animation::Medal.is_teleport());
        assert!(Animation::BackToEntrance.is_teleport());
        assert!(Animation::HornedRemains.is_teleport());
        assert!(Animation::LiurniaTowerDoor.is_teleport());
        assert!(Animation::PostBossWarp.is_teleport());
        assert!(Animation::ErdtreeBurn.is_teleport());
        assert!(Animation::PlacidusaxLieDown.is_teleport());
        assert!(Animation::AbductorVirginGrab.is_teleport());
        assert!(Animation::CoffinLakeOfRot.is_teleport());
        assert!(Animation::CoffinDeeproot.is_teleport());
    }

    #[test]
    fn test_non_teleport_animations() {
        assert!(!Animation::Spawn.is_teleport());
        assert!(!Animation::ItemUseMemory.is_teleport());
        assert!(!Animation::Bow.is_teleport());
        assert!(!Animation::OpenChest60080.is_teleport());
    }

    #[test]
    fn test_get_animation_label() {
        assert_eq!(get_animation_label(60060), "FogWall");
        assert_eq!(get_animation_label(60490), "Waygate");
        assert_eq!(get_animation_label(63000), "Spawn");
        assert_eq!(get_animation_label(0), "IDLE");
        assert_eq!(get_animation_label(12345), "12345"); // Unknown
    }

    #[test]
    fn test_get_teleport_type() {
        assert_eq!(get_teleport_type(60060), Some("FogWall".to_string()));
        assert_eq!(get_teleport_type(60490), Some("Waygate".to_string()));
        assert_eq!(
            get_teleport_type(60470),
            Some("SendingGateBlue".to_string())
        );
        assert_eq!(get_teleport_type(60472), Some("SendingGateRed".to_string()));
        assert_eq!(get_teleport_type(0), None);
        assert_eq!(get_teleport_type(63000), None); // Spawn is not a teleport
        assert_eq!(get_teleport_type(12345), None);
    }

    #[test]
    fn test_is_teleport_animation() {
        assert!(is_teleport_animation(60060));
        assert!(is_teleport_animation(60490));
        assert!(!is_teleport_animation(0));
        assert!(!is_teleport_animation(63000)); // Spawn
        assert!(!is_teleport_animation(12345)); // Unknown
    }

    #[test]
    fn test_animation_ids() {
        // Verify some key IDs are correct
        assert_eq!(Animation::FogWall as u32, 60060);
        assert_eq!(Animation::Waygate as u32, 60490);
        assert_eq!(Animation::Medal as u32, 50340);
        assert_eq!(Animation::Spawn as u32, 63000);
        assert_eq!(Animation::LiurniaTowerDoor as u32, 12202126);
        assert_eq!(Animation::PostBossWarp as u32, 12020210);
        assert_eq!(Animation::AbductorVirginGrab as u32, 15004000);
        assert_eq!(Animation::CoffinLakeOfRot as u32, 2020210);
        assert_eq!(Animation::CoffinDeeproot as u32, 2029050);
    }
}
