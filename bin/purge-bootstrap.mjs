import { PurgeCSS } from 'purgecss';
import { mkdirSync, writeFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, '..');
const templates = resolve(root, 'templates');
const vendor = resolve(root, 'static/vendor');

const safelist = {
  standard: [
    // Bootstrap JS runtime classes
    'collapsing', 'show', 'fade', 'active', 'collapsed',
    'modal-backdrop', 'modal-open',
    'offcanvas-backdrop', 'showing', 'hiding',
    'was-validated', 'disabled',
    // Third-party compatibility
    'popover', 'tooltip',
    // Dynamic icon ref'd by JS only (theme toggle)
    'bi-sun-fill',
  ],
  greedy: [
    // Bootstrap JS component classes
    /^modal-/,
    /^offcanvas-/,
    /^bs-/,
    /^carousel/,
    /^dropdown/,
    /^dropup/,
    /^popover/,
    /^tooltip/,
    /^collapse/,
    /^accordion/,
    // Bootstrap Icons — only keep the subset found in templates + JS
    // (exact list is auto-detected from content; the 'bi-sun-fill' standard
    //  safelist covers the only one missing from templates)
    // Dynamic button/badge/alert variants
    /^btn-/,
    /^badge-/,
    /^alert-/,
    /^text-bg-/,
    // Spacing utilities used dynamically
    /^m[tbsexy]?-/,
    /^p[tbsexy]?-/,
    /^gap-/,
    /^g-/,
    // Grid / layout
    /^col-/,
    /^row-cols-/,
    // Sizing
    /^w-/,
    /^h-/,
    /^mw-/,
    /^mh-/,
    /^min-vh-/,
    // Flex
    /^flex-/,
    /^justify-content-/,
    /^align-items-/,
    /^align-self-/,
    /^order-/,
    // Display
    /^d-/,
    /^float-/,
    // Position
    /^position-/,
    /^top-/,
    /^bottom-/,
    /^start-/,
    /^end-/,
    /^translate-/,
    // Overflow
    /^overflow-/,
    // Typography utilities
    /^text-/,
    /^fw-/,
    /^fs-/,
    /^lh-/,
    /^font-/,
    // Background / border
    /^bg-/,
    /^border/,
    /^rounded/,
    /^shadow/,
    // Opacity / visibility
    /^opacity-/,
    /^visible/,
    /^invisible/,
    // Interaction
    /^user-select-/,
    /^pe-/,
    /^pointer-event/,
    /^stretched-link/,
  ],
};

async function purgeFile(cssFile) {
  const outDir = dirname(cssFile);
  const result = await new PurgeCSS().purge({
    content: [
      `${templates}/**/*.html`,
      `${root}/static/js/**/*.js`,
      `${root}/static/service-worker.js`,
      `${root}/AI S/**/*.{tsx,ts,jsx}`,
    ],
    css: [cssFile],
    safelist,
    rejected: true,
  });
  const outPath = resolve(outDir, result[0].file);
  const original = result[0].css.length;
  writeFileSync(outPath, result[0].css);
  const rejected = result[0].rejected?.length || 0;
  return { file: cssFile, kept: result[0].css.length, rejected };
}

const cssFiles = [
  resolve(vendor, 'bootstrap/bootstrap.min.css'),
  resolve(vendor, 'bootstrap/bootstrap.rtl.min.css'),
  resolve(vendor, 'bootstrap-icons/bootstrap-icons.min.css'),
];

console.log('Purging Bootstrap CSS…\n');

for (const file of cssFiles) {
  const { kept, rejected } = await purgeFile(file);
  const name = file.split('/').pop();
  const kb = (kept / 1024).toFixed(0);
  console.log(`  ${name}: ${kb}KB kept (${rejected} selectors removed)`);
}

console.log('\nDone.');
