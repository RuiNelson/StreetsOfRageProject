/* Minimal shim replacing Genesis-Plus-GX/core/shared.h for the vendored
 * psg.c. The real shared.h pulls in GPGX's entire emulator-wide global
 * state; psg.c only ever touches two fields from it (`config.hq_psg` and
 * `snd.blips[0]`), so we declare just those instead. The matching
 * definitions live in Sound.cpp. */
#ifndef PSG_SHARED_H_
#define PSG_SHARED_H_

#include "blip_buf.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    unsigned char hq_psg;
} gpgx_config_t;

typedef struct {
    blip_t *blips[4];
} gpgx_snd_t;

extern gpgx_config_t config;
extern gpgx_snd_t    snd;

#ifdef __cplusplus
}
#endif

/* psg_context_save/load (unused — this project has no savestate support) call
 * GPGX's state.h save_param/load_param macros; stub them out as no-ops. */
#define save_param(param, size) ((void)0)
#define load_param(param, size) ((void)0)

#endif /* PSG_SHARED_H_ */
