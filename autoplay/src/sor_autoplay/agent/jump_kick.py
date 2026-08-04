"""Mathematical jump-kick solver (ROM physics).

Faithful discrete model of Streets of Rage unarmed jump + kick:

- C only → action ``$10`` crouch (5 frames) → ``$12`` free flight
- B edge in free flight → ``$16`` kick (never B+C on the same ground decision)
- 16.16-style velocities, character launch Z, air steer, lighter fall gravity
  while kicking

The solver predicts the full arc, when to press B, landing X, and which
enemies the moving kick box will hit. Policy uses that predicted effect to
choose whether a jump-kick is better than punch/grab — especially against
same-lane packs.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..phases import CombatPhase, is_punishable, should_ignore_as_target
from ..world_map import MapEntity
from .characters import CharacterProfile

# --- ROM constants (px / frame, 16.16 values / 65536) ---

CROUCH_FRAMES = 5
G_FULL = 0xE800 / 65536.0  # +0.90625
G_KICK_FALL = 0x8800 / 65536.0  # +0.53125
VZ0 = (-7.5, -8.5, -9.5)  # Axel, Adam, Blaze
VX_LAUNCH = 3.0
AIR_ACCEL = 0.375
VX_MAX = 3.5
VZ_MAX = 12.0
LANE_HALF = 8.0  # kick box y ±8
ENEMY_BODY_HALF_X = 12.0
ENEMY_BODY_HALF_Y = 12.0
ENEMY_BODY_Z0 = -50.0
ENEMY_BODY_Z1 = 0.0

# Attack AABB relative to player origin: (x0, x1, y0, y1, z0, z1)
# Facing right (action bit0 clear). Left facing mirrors X.
# Measured live from the attack box `+$64` during action $16 (ROM $450C
# compares attacker +$64 against victim +$70). The earlier values here were
# read from +$70 — the body box — and were roughly a third of the real reach.
_KICK_BOX_RIGHT: tuple[tuple[float, float, float, float, float, float], ...] = (
    (14.0, 42.0, -8.0, 8.0, -46.0, -19.0),  # Axel
    (17.0, 72.0, -8.0, 8.0, -43.0, -14.0),  # Adam
    (3.0, 49.0, -8.0, 8.0, -38.0, -6.0),  # Blaze
)

# Blaze kick anim bank c=$16 frame durations until active damage (f2/f3).
_BLAZE_FRAME_DUR = (3, 3, 3, 3)
_BLAZE_DMG_FROM_FRAME = 2

# Soft profile windows still used as a coarse approach band; solver is
# authoritative for connectability.
DEFAULT_MIN_DX = 16.0


@dataclass(frozen=True, slots=True)
class JumpKickHit:
    """One enemy the predicted kick would damage."""

    slot: str
    label: str
    first_hit_frame: int  # absolute sim frame index
    damage: int
    dx_at_hit: float


@dataclass(frozen=True, slots=True)
class JumpKickPlan:
    """Fully solved jump-kick parameters and predicted effect."""

    char_id: int
    face_left: bool
    hold_dir: int  # -1 left, +1 right (launch + air steer)
    kick_free_frame: int  # free-flight frame index to press B (0 = first free)
    crouch_frames: int
    air_frames: int
    total_frames: int
    landing_world_x: float
    landing_world_y: float
    range_x: float
    apex_rel_z: float
    hits: tuple[JumpKickHit, ...]
    primary_hit: bool
    ally_hit: bool
    total_damage: int
    score: float
    note: str = ""

    @property
    def hit_count(self) -> int:
        return len(self.hits)

    @property
    def multi_hit(self) -> bool:
        return self.hit_count >= 2


@dataclass
class JumpKickPending:
    """Seat memory: active jump-kick commitment after C is pressed."""

    face_left: bool = False
    hold_dir: int = 0
    kick_free_frame: int = 0
    free_frames_seen: int = 0
    primary_slot: str = ""
    expected_hits: int = 0
    score: float = 0.0
    active: bool = False

    def clear(self) -> None:
        self.active = False
        self.free_frames_seen = 0
        self.primary_slot = ""
        self.expected_hits = 0
        self.score = 0.0

    def arm(
        self,
        plan: JumpKickPlan,
        *,
        primary_slot: str = "",
    ) -> None:
        self.face_left = plan.face_left
        self.hold_dir = plan.hold_dir
        self.kick_free_frame = max(0, int(plan.kick_free_frame))
        self.free_frames_seen = 0
        self.primary_slot = primary_slot
        self.expected_hits = plan.hit_count
        self.score = plan.score
        self.active = True


def char_id_from_profile(profile: CharacterProfile) -> int:
    for cid, prof in ((0, "Axel"), (1, "Adam"), (2, "Blaze")):
        if profile.name == prof:
            return cid
    return 0


def kick_box(
    char_id: int, *, face_left: bool
) -> tuple[float, float, float, float, float, float]:
    """Return (x0, x1, y0, y1, z0, z1) relative to the player."""

    cid = 0 if char_id < 0 or char_id > 2 else char_id
    x0, x1, y0, y1, z0, z1 = _KICK_BOX_RIGHT[cid]
    if face_left:
        return (-x1, -x0, y0, y1, z0, z1)
    return (x0, x1, y0, y1, z0, z1)


def damage_on_kick_frame(char_id: int, kick_age: int) -> int:
    """Outgoing damage nibble for the Nth frame of the kick state (0-based)."""

    if char_id == 2:
        # Advance Blaze frames by duration table until frame 3.
        age = kick_age
        frame = 0
        for dur in _BLAZE_FRAME_DUR:
            if age < dur:
                break
            age -= dur
            frame += 1
            if frame >= 3:
                frame = 3
                break
        return 2 if frame >= _BLAZE_DMG_FROM_FRAME else 0
    # Axel / Adam: frame 0 pose for the whole kick, damage 3.
    return 3


def _aabb_overlap(
    a0: float,
    a1: float,
    b0: float,
    b1: float,
) -> bool:
    return not (a1 < b0 or a0 > b1)


def _enemy_eligible(entity: MapEntity) -> bool:
    if entity.kind not in ("enemy", "boss"):
        return False
    if entity.is_defeated:
        return False
    if should_ignore_as_target(entity.combat_phase):
        return False
    if entity.combat_phase == CombatPhase.GRABBED:
        return False
    return True


@dataclass
class _SimFrame:
    t: int
    free_i: int  # -1 crouch, >=0 free/kick index
    kicking: bool
    kick_age: int
    x: float
    y: float
    z: float  # absolute
    z_rel: float  # relative to ground (negative = up)
    vx: float
    vz: float
    face_left: bool


def _simulate_arc(
    *,
    char_id: int,
    start_x: float,
    start_y: float,
    z_ground: float,
    hold_dir: int,
    face_left: bool,
    kick_free_frame: int | None,
    max_frames: int = 80,
) -> list[_SimFrame]:
    """Simulate crouch + flight. ``kick_free_frame=None`` means never kick."""

    cid = 0 if char_id < 0 or char_id > 2 else char_id
    vz0 = VZ0[cid]
    x = float(start_x)
    y = float(start_y)
    z = float(z_ground)
    vx = 0.0
    vz = 0.0
    facing_left = face_left
    frames: list[_SimFrame] = []
    t = 0

    # Crouch: velocities zeroed by ROM.
    for _ in range(CROUCH_FRAMES):
        frames.append(
            _SimFrame(
                t=t,
                free_i=-1,
                kicking=False,
                kick_age=0,
                x=x,
                y=y,
                z=z,
                z_rel=0.0,
                vx=vx,
                vz=vz,
                face_left=facing_left,
            )
        )
        t += 1

    # Launch.
    vz = vz0
    if hold_dir < 0:
        vx = -VX_LAUNCH
        facing_left = True
    elif hold_dir > 0:
        vx = VX_LAUNCH
        facing_left = False
    else:
        vx = 0.0

    kicking = False
    kick_age = 0
    free_i = 0
    landed = False

    while free_i < max_frames and not landed:
        # Enter kick on this free-flight frame *before* physics if scheduled.
        if (
            kick_free_frame is not None
            and not kicking
            and free_i >= kick_free_frame
        ):
            kicking = True
            kick_age = 0

        if free_i == 0:
            # Transition frame: no gravity yet (matches $1FC0 then integrate).
            pass
        else:
            if kicking and vz >= 0.0:
                vz += G_KICK_FALL
            else:
                vz += G_FULL
            if hold_dir < 0:
                vx -= AIR_ACCEL
                facing_left = True
            elif hold_dir > 0:
                vx += AIR_ACCEL
                facing_left = False
            if vx > VX_MAX:
                vx = VX_MAX
            elif vx < -VX_MAX:
                vx = -VX_MAX
            if vz > VZ_MAX:
                vz = VZ_MAX

        x += vx
        z += vz
        z_rel = z - z_ground

        frames.append(
            _SimFrame(
                t=t,
                free_i=free_i,
                kicking=kicking,
                kick_age=kick_age if kicking else 0,
                x=x,
                y=y,
                z=z,
                z_rel=z_rel,
                vx=vx,
                vz=vz,
                face_left=facing_left,
            )
        )
        t += 1

        if free_i > 0 and z_rel >= 0.0 and vz >= 0.0:
            landed = True
            break

        if kicking:
            kick_age += 1
        free_i += 1

    return frames


def _height_ok(fr: _SimFrame, other_z: float) -> bool:
    """Z gate: strict AABB when possible, else practical mid-arc engagement.

    Exact ROM player/enemy Z boxes are animation-dependent. Live jump-kicks
    still connect through much of the arc against grounded foes, so when the
    strict band misses we accept frames where the player is within a combat
    height of the foe's ground plane.
    """

    return abs(fr.z - other_z) <= 72.0 and abs(fr.z_rel) <= 58.0


def _collect_hits(
    frames: list[_SimFrame],
    *,
    char_id: int,
    foes: tuple[MapEntity, ...],
    partner: MapEntity | None,
) -> tuple[tuple[JumpKickHit, ...], bool]:
    hits: list[JumpKickHit] = []
    hit_slots: set[str] = set()
    ally_hit = False

    for fr in frames:
        if not fr.kicking:
            continue
        dmg = damage_on_kick_frame(char_id, fr.kick_age)
        if dmg <= 0:
            continue
        x0, x1, y0, y1, z0, z1 = kick_box(char_id, face_left=fr.face_left)
        ax0, ax1 = fr.x + x0, fr.x + x1
        ay0, ay1 = fr.y + y0, fr.y + y1
        az0, az1 = fr.z + z0, fr.z + z1

        if partner is not None and partner.kind == "player":
            px0 = float(partner.world_x) - ENEMY_BODY_HALF_X
            px1 = float(partner.world_x) + ENEMY_BODY_HALF_X
            py0 = float(partner.world_y) - ENEMY_BODY_HALF_Y
            py1 = float(partner.world_y) + ENEMY_BODY_HALF_Y
            pz0 = float(partner.world_z) + ENEMY_BODY_Z0
            pz1 = float(partner.world_z) + ENEMY_BODY_Z1
            if (
                _aabb_overlap(ax0, ax1, px0, px1)
                and _aabb_overlap(ay0, ay1, py0, py1)
                and (
                    _aabb_overlap(az0, az1, pz0, pz1)
                    or _height_ok(fr, float(partner.world_z))
                )
            ):
                ally_hit = True

        for foe in foes:
            if foe.slot in hit_slots:
                continue
            if not _enemy_eligible(foe):
                continue
            fx0 = float(foe.world_x) - ENEMY_BODY_HALF_X
            fx1 = float(foe.world_x) + ENEMY_BODY_HALF_X
            fy0 = float(foe.world_y) - ENEMY_BODY_HALF_Y
            fy1 = float(foe.world_y) + ENEMY_BODY_HALF_Y
            fz0 = float(foe.world_z) + ENEMY_BODY_Z0
            fz1 = float(foe.world_z) + ENEMY_BODY_Z1
            if not _aabb_overlap(ax0, ax1, fx0, fx1):
                continue
            if not _aabb_overlap(ay0, ay1, fy0, fy1):
                continue
            if not (
                _aabb_overlap(az0, az1, fz0, fz1)
                or _height_ok(fr, float(foe.world_z))
            ):
                continue
            hit_slots.add(foe.slot)
            hits.append(
                JumpKickHit(
                    slot=foe.slot,
                    label=foe.label,
                    first_hit_frame=fr.t,
                    damage=dmg,
                    dx_at_hit=float(foe.world_x) - fr.x,
                )
            )

    return tuple(hits), ally_hit


def _score_plan(
    hits: tuple[JumpKickHit, ...],
    *,
    primary_slot: str | None,
    ally_hit: bool,
    profile: CharacterProfile,
    punish_bonus: float,
) -> float:
    if ally_hit:
        return -1.0
    if not hits:
        return 0.0
    score = 0.0
    primary_hit = False
    for h in hits:
        score += 1.0 + 0.08 * h.damage
        if primary_slot and h.slot == primary_slot:
            primary_hit = True
            score += 0.85
    # Multi-enemy is the main strategic value of this move.
    if len(hits) >= 2:
        score += 1.35 * (len(hits) - 1)
    if len(hits) >= 3:
        score += 0.75
    if primary_hit:
        score += 0.25 * profile.jump_attack_bias
    score += punish_bonus
    return score


def solve_jump_kick(
    me: MapEntity,
    entities: tuple[MapEntity, ...],
    profile: CharacterProfile,
    *,
    primary: MapEntity | None = None,
    partner: MapEntity | None = None,
    char_id: int | None = None,
    prefer_face_left: bool | None = None,
) -> JumpKickPlan | None:
    """Search launch direction and B timing; return the best scoring plan.

    Returns ``None`` when no plan hits any eligible enemy without clipping the
    partner. The score encodes multi-hit value so policy can prefer pack kicks.
    """

    cid = char_id if char_id is not None else char_id_from_profile(profile)
    foes = tuple(e for e in entities if _enemy_eligible(e))
    if not foes and primary is None:
        return None

    z_g = float(me.world_z)
    start_x = float(me.world_x)
    start_y = float(me.world_y)

    # Candidate facings / hold dirs: toward primary, else both sides.
    dirs: list[tuple[bool, int]] = []
    if primary is not None:
        toward_left = primary.world_x < me.world_x
        d = -1 if toward_left else 1
        dirs.append((toward_left, d))
        # Also try facing toward but zero launch (rare) and opposite only if
        # multi-hit might prefer it — keep search small.
        dirs.append((toward_left, 0))
    if prefer_face_left is not None:
        d = -1 if prefer_face_left else 1
        dirs.append((prefer_face_left, d))
    # Always consider both full launches for pack geometry.
    dirs.append((True, -1))
    dirs.append((False, 1))
    # Dedupe preserving order.
    seen: set[tuple[bool, int]] = set()
    uniq_dirs: list[tuple[bool, int]] = []
    for item in dirs:
        if item not in seen:
            seen.add(item)
            uniq_dirs.append(item)

    primary_slot = primary.slot if primary is not None else None
    punish_bonus = 0.0
    if primary is not None and is_punishable(primary.combat_phase):
        punish_bonus = 0.4

    best: JumpKickPlan | None = None

    for face_left, hold_dir in uniq_dirs:
        # Bound free-flight length without kick for kick-frame search.
        base_frames = _simulate_arc(
            char_id=cid,
            start_x=start_x,
            start_y=start_y,
            z_ground=z_g,
            hold_dir=hold_dir,
            face_left=face_left,
            kick_free_frame=None,
        )
        free_len = sum(1 for f in base_frames if f.free_i >= 0)
        if free_len <= 0:
            continue
        # Try B on a subset of free-flight frames (every frame is cheap).
        for kick_at in range(0, free_len):
            frames = _simulate_arc(
                char_id=cid,
                start_x=start_x,
                start_y=start_y,
                z_ground=z_g,
                hold_dir=hold_dir,
                face_left=face_left,
                kick_free_frame=kick_at,
            )
            hits, ally_hit = _collect_hits(
                frames, char_id=cid, foes=foes, partner=partner
            )
            score = _score_plan(
                hits,
                primary_slot=primary_slot,
                ally_hit=ally_hit,
                profile=profile,
                punish_bonus=punish_bonus,
            )
            if score <= 0.0:
                continue
            primary_hit = any(h.slot == primary_slot for h in hits) if primary_slot else bool(hits)
            # Prefer plans that hit the primary when one was requested.
            if primary_slot is not None and not primary_hit:
                score *= 0.35
            land = next((f for f in reversed(frames) if f.free_i >= 0), frames[-1])
            air = sum(1 for f in frames if f.free_i >= 0)
            apex = min((f.z_rel for f in frames), default=0.0)
            plan = JumpKickPlan(
                char_id=cid,
                face_left=land.face_left if hold_dir == 0 else face_left,
                hold_dir=hold_dir,
                kick_free_frame=kick_at,
                crouch_frames=CROUCH_FRAMES,
                air_frames=air,
                total_frames=len(frames),
                landing_world_x=land.x,
                landing_world_y=start_y,
                range_x=abs(land.x - start_x),
                apex_rel_z=apex,
                hits=hits,
                primary_hit=primary_hit,
                ally_hit=ally_hit,
                total_damage=sum(h.damage for h in hits),
                score=score,
                note=(
                    f"jk×{len(hits)} dmg={sum(h.damage for h in hits)} "
                    f"B@{kick_at} land={land.x - start_x:+.0f}"
                ),
            )
            if best is None or plan.score > best.score + 1e-6:
                best = plan
            elif best is not None and abs(plan.score - best.score) <= 1e-6:
                # Tie-break: earlier B, more hits, shorter total time.
                if plan.hit_count > best.hit_count:
                    best = plan
                elif plan.hit_count == best.hit_count and plan.kick_free_frame < best.kick_free_frame:
                    best = plan

    return best


def plan_connects(
    plan: JumpKickPlan | None,
    *,
    require_primary: bool = False,
) -> bool:
    if plan is None or plan.ally_hit or plan.hit_count <= 0:
        return False
    if require_primary and not plan.primary_hit:
        return False
    return plan.score > 0.0


def can_jump_kick_solved(
    me: MapEntity,
    foe: MapEntity,
    profile: CharacterProfile,
    *,
    entities: tuple[MapEntity, ...] | None = None,
    partner: MapEntity | None = None,
    loose_lane: bool = False,
) -> tuple[bool, JumpKickPlan | None]:
    """Solver-backed jump-kick readiness for a primary foe (and optional pack).

    Returns ``(ok, plan)``. ``ok`` means the best plan damages the primary (or,
    when only a pack is considered, any foe) without hitting the partner.
    """

    lane = LANE_HALF + (6.0 if loose_lane else 4.0)
    if abs(foe.world_y - me.world_y) > lane + ENEMY_BODY_HALF_Y:
        # Far off-lane: still allow solver if pack Y might work, but primary
        # must share lane for a targeted kick.
        if abs(foe.map_y - me.map_y) > lane + ENEMY_BODY_HALF_Y:
            return False, None

    pool = entities if entities is not None else (foe,)
    plan = solve_jump_kick(
        me,
        pool,
        profile,
        primary=foe,
        partner=partner,
    )
    if plan is None:
        return False, None
    if plan.ally_hit:
        return False, plan
    if not plan.primary_hit and foe.slot:
        # Accept multi-only packs only when primary is among hits.
        return False, plan
    # Reject absurdly short or long geometric misses relative to profile soft
    # band — still allow solver range slightly outside FAQ max.
    abs_dx = abs(foe.world_x - me.world_x)
    soft_max = max(profile.jump_kick_max + 12.0, plan.range_x + 8.0)
    if abs_dx < DEFAULT_MIN_DX or abs_dx > soft_max + 40.0:
        # Very far: only accept if the solved landing still reaches them.
        if not plan.primary_hit:
            return False, plan
    return plan.primary_hit and plan.score > 0.0, plan


def predict_landing(
    me: MapEntity,
    profile: CharacterProfile,
    *,
    face_left: bool,
    hold_dir: int,
    kick_free_frame: int = 0,
    char_id: int | None = None,
) -> tuple[float, float]:
    """Landing world (x, y) for navigation safety checks."""

    cid = char_id if char_id is not None else char_id_from_profile(profile)
    frames = _simulate_arc(
        char_id=cid,
        start_x=float(me.world_x),
        start_y=float(me.world_y),
        z_ground=float(me.world_z),
        hold_dir=hold_dir,
        face_left=face_left,
        kick_free_frame=kick_free_frame,
    )
    land = next((f for f in reversed(frames) if f.free_i >= 0), frames[-1])
    return land.x, float(me.world_y)


__all__ = [
    "CROUCH_FRAMES",
    "JumpKickHit",
    "JumpKickPending",
    "JumpKickPlan",
    "can_jump_kick_solved",
    "char_id_from_profile",
    "damage_on_kick_frame",
    "kick_box",
    "plan_connects",
    "predict_landing",
    "solve_jump_kick",
]
