# VibeSensor Wire Protocol (v1)

All multi-byte numeric fields use little-endian encoding.

## Message types

- `1`: HELLO
- `2`: DATA
- `3`: CMD
- `4`: ACK

## Field layout

- `client_id`: 6 bytes (MAC-derived)
- HELLO fixed bytes (without name/fw payload bytes): `18`
- DATA header bytes (without sample payload): `22`
- CMD header bytes: `13`
- CMD identify bytes: `15`
- ACK bytes: `13`

## HELLO (`type=1`)

- `u8 type`
- `u8 version`
- `u8[6] client_id`
- `u16 control_port`
- `u16 sample_rate_hz`
- `u8 name_len`
- `u8[name_len] name_utf8`
- `u8 fw_len`
- `u8[fw_len] firmware_utf8`
- `u32 queue_overflow_drops`

## DATA (`type=2`)

- `u8 type`
- `u8 version`
- `u8[6] client_id`
- `u32 seq`
- `u64 t0_us`
- `u16 sample_count`
- `i16[sample_count*3] xyz_interleaved`

## CMD (`type=3`)

- `u8 type`
- `u8 version`
- `u8[6] client_id`
- `u8 cmd_id`
- `u32 cmd_seq`
- params by `cmd_id` (`identify`: `u16 duration_ms`)

## ACK (`type=4`)

- `u8 type`
- `u8 version`
- `u8[6] client_id`
- `u32 cmd_seq`
- `u8 status`
