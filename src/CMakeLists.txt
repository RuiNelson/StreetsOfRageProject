cmake_minimum_required(VERSION 3.24)
project(sor LANGUAGES CXX C)

# ── C++ standard ─────────────────────────────────────────────────────────────
set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# ── C standard (vendored Genesis-Plus-GX cores: Z80, YM2612, PSG, blip_buf) ───
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

# Suppress CMake 3.27+ policy warnings emitted by FetchContent subprojects
# (e.g. yaml-cpp) that declare an older cmake_minimum_required version.
set(CMAKE_POLICY_VERSION_MINIMUM 3.5)

# ── System dependencies ───────────────────────────────────────────────────────
find_package(SDL3 REQUIRED)

# ── Fetched dependencies ──────────────────────────────────────────────────────
include(FetchContent)

FetchContent_Declare(
    yaml-cpp
    GIT_REPOSITORY https://github.com/jbeder/yaml-cpp.git
    GIT_TAG        yaml-cpp-0.9.0
)

FetchContent_Declare(
    zlib
    GIT_REPOSITORY https://github.com/madler/zlib.git
    GIT_TAG        v1.3.1
)

FetchContent_Declare(
    libpng
    GIT_REPOSITORY https://github.com/pnggroup/libpng.git
    GIT_TAG        v1.6.47
)

FetchContent_Declare(
    CLI11
    GIT_REPOSITORY https://github.com/CLIUtils/CLI11.git
    GIT_TAG        v2.4.2
)

# Only the static libraries are linked into `sor`. Disable every other target
# the dependencies would otherwise build — libpng's shared lib, Apple framework,
# tools, tests and example, plus zlib's examples. Those extra targets are
# fragile here (the libpng framework/example builds break on this toolchain) and
# are never used, so building them only introduces failures.
set(SKIP_INSTALL_ALL ON CACHE BOOL "" FORCE)

# zlib
set(ZLIB_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)

# libpng
set(PNG_SHARED      OFF CACHE BOOL "" FORCE)
set(PNG_STATIC      ON  CACHE BOOL "" FORCE)
set(PNG_FRAMEWORK   OFF CACHE BOOL "" FORCE)
set(PNG_TESTS       OFF CACHE BOOL "" FORCE)
set(PNG_TOOLS       OFF CACHE BOOL "" FORCE)
set(PNG_EXECUTABLES OFF CACHE BOOL "" FORCE) # older libpng option name for tools

# Make zlib available first — libpng depends on it.
FetchContent_MakeAvailable(yaml-cpp zlib)
FetchContent_MakeAvailable(libpng)
FetchContent_MakeAvailable(CLI11)

# ── Sources ───────────────────────────────────────────────────────────────────
file(GLOB_RECURSE SOR_SOURCES CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/*.cpp")
list(FILTER SOR_SOURCES EXCLUDE REGEX ".*/_deps/.*")
list(FILTER SOR_SOURCES EXCLUDE REGEX ".*/build/.*")

# Vendored Genesis-Plus-GX C cores (Z80 CPU, YM2612, PSG, blip_buf) — kept out
# of the *.cpp glob above since they're plain C, not C++.
file(GLOB GPGX_C_SOURCES CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/system/z80/gpgx_z80/*.c"
    "${CMAKE_CURRENT_SOURCE_DIR}/system/sound/gpgx_sound/*.c"
)
list(APPEND SOR_SOURCES ${GPGX_C_SOURCES})

# ym3438.c's entire body is gated behind HAVE_YM3438_CORE (GPGX selects FM
# cores at build time via this define); we only ever build the one core.
set_source_files_properties(
    "${CMAKE_CURRENT_SOURCE_DIR}/system/sound/gpgx_sound/ym3438.c"
    PROPERTIES COMPILE_DEFINITIONS HAVE_YM3438_CORE
)

# z80.c's PAIR union and types.h's reg16_t union pick their in-memory byte
# layout based on LSB_FIRST. This project only targets little-endian hosts
# (x86_64/ARM64), so it must always be defined — without it, the union's
# `.w.l`/`.b.l` accessors alias the *wrong* half of the 32-bit value on a
# little-endian machine (the Z80 core's "PC" macro silently incremented bits
# 16-31 instead of 0-15, corrupting the program counter within a few
# instructions).
set_property(
    SOURCE ${GPGX_C_SOURCES}
    APPEND PROPERTY COMPILE_DEFINITIONS LSB_FIRST
)

# ── Target ────────────────────────────────────────────────────────────────────
add_executable(sor ${SOR_SOURCES})

# The recompiler emits backward branches/loops as tail-recursive calls
# (`sub_xxxx(...); return;`), not real loops — they only stay stack-bounded
# under sibling-call optimization (-O2/-O3). A Debug build (-O0) stack-overflows
# within the first boot-time decompression loop. Force -O2 for just this file
# in Debug so TCO applies and the game boots; the rest of the project stays
# -O0/debuggable. No-op in Release/RelWithDebInfo, which already optimize.
set_source_files_properties(
    "${CMAKE_CURRENT_SOURCE_DIR}/generated/Sor.cpp"
    PROPERTIES COMPILE_OPTIONS "$<$<CONFIG:Debug>:-O2>"
)

# The vendored cores are untouched third-party C; don't hold them to this
# project's C++ warning level.
set_source_files_properties(${GPGX_C_SOURCES} PROPERTIES COMPILE_OPTIONS -w)

target_include_directories(sor PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/generated
    ${CMAKE_CURRENT_SOURCE_DIR}/system
    ${CMAKE_CURRENT_SOURCE_DIR}/system/cpu
    ${CMAKE_CURRENT_SOURCE_DIR}/system/memory
    ${CMAKE_CURRENT_SOURCE_DIR}/system/graphics
    ${CMAKE_CURRENT_SOURCE_DIR}/system/controllers
    ${CMAKE_CURRENT_SOURCE_DIR}/system/sound
    ${CMAKE_CURRENT_SOURCE_DIR}/system/sound/gpgx_sound
    ${CMAKE_CURRENT_SOURCE_DIR}/system/z80
    ${CMAKE_CURRENT_SOURCE_DIR}/system/z80/gpgx_z80
    ${CMAKE_CURRENT_SOURCE_DIR}/config
    ${CMAKE_CURRENT_SOURCE_DIR}/util
)

target_link_libraries(sor PRIVATE
    SDL3::SDL3
    yaml-cpp::yaml-cpp
    png_static
    zlibstatic
    CLI11::CLI11
)
