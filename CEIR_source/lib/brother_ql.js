// Pure-JS port of brother_ql for Brother QL-820NWB on 62mm continuous tape.
// Byte-for-byte compatible with the Python `brother_ql` package — verified
// against a reference dump from the same printer.
//
// Inputs:
//   - rasterImage1bit: Uint8Array of length (90 × heightPx). One bit per
//     pixel, MSB-first, 720 bits per row (90 bytes), pixel value 1 = print
//     black.
//   - heightPx: number of raster rows (image height in pixels)
//
// Output: Buffer of raw bytes to send to the printer via `lpr -oraw`.

// QL-820NWB on 62mm continuous spec ─────────────────────────────────────────
const DEVICE_PIXEL_WIDTH = 720;       // bytes_per_row × 8 = 90 × 8
const BYTES_PER_ROW      = 90;
const DOTS_PRINTABLE     = 696;       // 62mm at 300 DPI
const RIGHT_MARGIN_DOTS  = 12;        // padding before mirror
const FEED_MARGIN        = 35;
const MEDIA_TYPE_ENDLESS = 0x0A;
const TAPE_WIDTH_MM      = 62;

/**
 * Build the full byte stream for printing one image on a QL-820NWB / 62mm tape.
 *
 * @param {object} opts
 * @param {Buffer|Uint8Array} opts.bits1   1-bit packed raster, 90 bytes per row, top-to-bottom.
 *                                          Bits set to 1 = black pixel.
 * @param {number} opts.height             Number of raster rows.
 * @returns {Buffer}
 */
function buildRaster({ bits1, height }) {
  const expectedLen = BYTES_PER_ROW * height;
  if (bits1.length !== expectedLen) {
    throw new Error(`Bad raster length: got ${bits1.length}, expected ${expectedLen}`);
  }

  const chunks = [];

  // 1) Switch mode (called TWICE in convert() — once before invalidate, once after init)
  chunks.push(Buffer.from([0x1B, 0x69, 0x61, 0x01]));     // ESC i a 01

  // 2) Invalidate — 200 zero bytes
  chunks.push(Buffer.alloc(200, 0x00));

  // 3) Initialize
  chunks.push(Buffer.from([0x1B, 0x40]));                 // ESC @

  // 4) Switch mode again
  chunks.push(Buffer.from([0x1B, 0x69, 0x61, 0x01]));

  // 5) Status info request
  chunks.push(Buffer.from([0x1B, 0x69, 0x53]));           // ESC i S

  // 6) Media + quality (ESC i z + 10 byte payload)
  //
  //    valid flags = 0x80 | (mtype set) << 1 | (mwidth set) << 2 | (mlength set) << 3 | pquality << 6
  //                = 0x80 | 0x02 | 0x04 | 0x08 | 0x40 = 0xCE
  //    mtype       = 0x0A (continuous)
  //    mwidth      = 62
  //    mlength     = 0  (endless)
  //    rnumber     = raster line count (little-endian uint32)
  //    page_num    = 0 for first page
  //    last byte   = 0x00
  const mediaQ = Buffer.alloc(13);
  mediaQ[0]  = 0x1B; mediaQ[1] = 0x69; mediaQ[2] = 0x7A;
  mediaQ[3]  = 0xCE;
  mediaQ[4]  = MEDIA_TYPE_ENDLESS;
  mediaQ[5]  = TAPE_WIDTH_MM;
  mediaQ[6]  = 0;                                          // mlength
  mediaQ.writeUInt32LE(height, 7);                         // rnumber
  mediaQ[11] = 0;                                          // page_number (0 = first)
  mediaQ[12] = 0;
  chunks.push(mediaQ);

  // 7) Autocut on
  chunks.push(Buffer.from([0x1B, 0x69, 0x4D, 0x40]));     // ESC i M 0x40

  // 8) Cut every 1 label
  chunks.push(Buffer.from([0x1B, 0x69, 0x41, 0x01]));     // ESC i A 01

  // 9) Expanded mode: cut_at_end (bit 3) = 0x08
  chunks.push(Buffer.from([0x1B, 0x69, 0x4B, 0x08]));     // ESC i K 0x08

  // 10) Margins (feed_margin = 35 = 0x23)
  const margins = Buffer.alloc(5);
  margins[0] = 0x1B; margins[1] = 0x69; margins[2] = 0x64;
  margins.writeUInt16LE(FEED_MARGIN, 3);
  chunks.push(margins);

  // (no compression — we send uncompressed)

  // 11) Raster data — one row at a time.
  //     Each row prefix: 0x67 0x00 0x5A (= 90), then 90 bytes.
  for (let row = 0; row < height; row++) {
    chunks.push(Buffer.from([0x67, 0x00, BYTES_PER_ROW]));
    chunks.push(Buffer.from(bits1.subarray(row * BYTES_PER_ROW, (row + 1) * BYTES_PER_ROW)));
  }

  // 12) Print + eject (last page)
  chunks.push(Buffer.from([0x1A]));

  return Buffer.concat(chunks);
}

/**
 * Convert a grayscale image (raw 8-bit single-channel) into 1-bit packed
 * bytes ready for buildRaster(). Replicates the conversion logic from
 * brother_ql.conversion.convert() for ENDLESS_LABEL:
 *
 *   1. Take grayscale image of width DOTS_PRINTABLE (696).
 *   2. Paste into a DEVICE_PIXEL_WIDTH (720) wide canvas of WHITE, at x = 720 - 696 - 12 = 12.
 *      So our 696-wide content sits at columns [12 .. 707], with 12 white margin on the LEFT (after mirror — see step 4).
 *   3. Invert: black (0) → 255, white (255) → 0.
 *   4. Threshold: pixel > threshold → 255 (= 1 bit, will print black).
 *   5. Mirror horizontally (FLIP_LEFT_RIGHT).
 *   6. Pack bits MSB-first into 90 bytes per row.
 *
 * @param {Buffer|Uint8Array} gray   Grayscale bytes (width × height).
 * @param {number} width             Must be DOTS_PRINTABLE (696).
 * @param {number} height
 * @param {number} threshold         0–255; brother_ql default is 70 (% → 178 inverted).
 * @returns {{bits1: Buffer, height: number}}
 */
function grayscaleToBrotherRaster(gray, width, height, threshold = 178) {
  if (width !== DOTS_PRINTABLE) {
    throw new Error(`grayscaleToBrotherRaster expects width=${DOTS_PRINTABLE}, got ${width}`);
  }
  // PIL threshold logic: int((100 - threshold)/100 * 255). brother_ql default threshold arg = 70.
  // So thresholdLevel = (100-70)/100 * 255 = 76.5 ≈ 76.
  // After invert, "pixel < threshold → 0, else 255". We replicate that.

  const bits1 = Buffer.alloc(BYTES_PER_ROW * height, 0x00);

  for (let y = 0; y < height; y++) {
    // Step 2+3+4: build a 720-wide row of black/white pixels.
    //
    // We DO NOT need a separate canvas; we just compute, for each output
    // column x_out (0..719), what value it would be after invert+threshold+mirror.
    //
    // Mirror first → original column ix_in = 719 - x_out.
    // ix_in falls into:
    //   ix_in <  12              → padded white  → after invert = 0 → < threshold → 0 (bit OFF)
    //   12 <= ix_in <  12 + 696  → image pixel at column (ix_in - 12)
    //   ix_in >= 708             → padded white  → after invert = 0 → bit OFF
    for (let xOut = 0; xOut < DEVICE_PIXEL_WIDTH; xOut++) {
      const ixIn = (DEVICE_PIXEL_WIDTH - 1) - xOut;
      let pixel; // pre-invert grayscale
      if (ixIn < RIGHT_MARGIN_DOTS) {
        pixel = 255;                                       // white margin
      } else {
        const ixContent = ixIn - RIGHT_MARGIN_DOTS;
        if (ixContent >= width) {
          pixel = 255;
        } else {
          pixel = gray[y * width + ixContent];
        }
      }
      const inverted = 255 - pixel;
      // PIL `point(lambda x: 0 if x < threshold else 255, mode='1')`
      // → bit value = inverted >= threshold ? 1 : 0
      if (inverted >= threshold) {
        const byteIdx = (y * BYTES_PER_ROW) + (xOut >> 3);
        const bitIdx  = 7 - (xOut & 7);
        bits1[byteIdx] |= (1 << bitIdx);
      }
    }
  }
  return { bits1, height };
}

module.exports = {
  DOTS_PRINTABLE, DEVICE_PIXEL_WIDTH, BYTES_PER_ROW,
  buildRaster, grayscaleToBrotherRaster,
};
