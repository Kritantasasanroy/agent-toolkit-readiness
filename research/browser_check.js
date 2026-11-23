// The browser pass of the evidence check, run through the BrowserOS `run` tool.
// For every citation the plain fetch could not confirm, open the page in a real browser,
// wait for it to render, and test the quote against the visible text. The matching rules
// are the same as Page.normalise in research/links.py.
const norm = s => s.normalize("NFKC")
  .replace(/[‘’]/g, "'").replace(/[“”]/g, '"').replace(/[–—]/g, "-")
  .replace(/[`*]/g, "").replace(/\s+/g, " ")
  .replace(/ ([.,;:!?)\]])/g, "$1").replace(/([(\[]) /g, "$1").trim().toLowerCase();

async function check(url, quotes) {
  const page = await browser.pages.newPage(url);
  const id = page.pageId ?? page.id ?? page;
  await new Promise(done => setTimeout(done, 6000));
  const expression = `(() => { const norm = ${norm}; const text = norm(document.body.innerText);
    return JSON.stringify(${JSON.stringify(quotes)}.map(q => { const n = norm(q); return n !== "" && text.includes(n); })); })()`;
  const reply = await browser.cdpJsonForPage(id, "Runtime.evaluate", JSON.stringify({ expression, returnByValue: true }));
  await browser.pages.close(id);
  return reply;
}
