import puppeteer from 'puppeteer-core';
const [out, wait, mode] = [process.argv[2], Number(process.argv[3] ?? 5000), process.argv[4]];
const b = await puppeteer.launch({ executablePath: '/usr/bin/google-chrome', headless: 'new',
  args: ['--no-sandbox', '--hide-scrollbars', '--use-gl=angle', '--use-angle=swiftshader',
         '--enable-unsafe-swiftshader', '--window-size=1600,1000'] });
const p = await b.newPage();
await p.setViewport({ width: 1600, height: 1000 });
const errs = [];
p.on('pageerror', e => errs.push(String(e)));
await p.goto('http://localhost:5173', { waitUntil: 'networkidle2' });
await new Promise(r => setTimeout(r, 3000));
if (mode) {
  await p.evaluate((m) => [...document.querySelectorAll('button')]
    .find(b => b.textContent.trim() === m)?.click(), mode);
}
await new Promise(r => setTimeout(r, wait));
await p.screenshot({ path: out });
console.log(errs.length ? 'ERRORS: ' + [...new Set(errs)].slice(0,4).join(' | ') : 'no errors');
await b.close();
