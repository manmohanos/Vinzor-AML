// The journey a compliance officer actually walks, driven in a real browser.
//
// Everything under tests/ in Python proves the engine is right. Nothing
// proved the *screens* were there. Three features shipped in the last two
// days computed correctly, served correctly over the API, and rendered
// nowhere -- the regulatory page had been API-only since it was written,
// and I only found that by driving a browser by hand. This is that check,
// automated.
//
// So these assertions are deliberately about *presence and honesty of
// wording*, not about pixels. A screenshot baseline would fail on every
// font change and teach whoever inherits it to press "update snapshots"
// without reading. What must never regress is that a figure appears at all,
// and that the sentences qualifying it appear beside it.

const { test, expect } = require("@playwright/test");

// The demo workspace enrols these; the first is an AML Officer.
async function signIn(page) {
  await page.goto("/");
  const door = page.locator("button", { hasText: "Meera Nair" });
  await expect(door).toBeVisible();
  await door.click();
  await expect(page.locator(".rail-nav")).toBeVisible();
}

test.describe("the officer journey", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page);
  });

  test("every screen in the rail opens and renders something", async ({
    page,
  }) => {
    // The failure this catches: a route that throws, or renders an empty
    // shell. Both look identical to "nothing is wrong" from the API side.
    const rail = page.locator(".rail-nav a");
    const count = await rail.count();
    expect(count).toBeGreaterThan(4);

    for (let i = 0; i < count; i++) {
      const link = rail.nth(i);
      const label = (await link.textContent()).trim();
      await link.click();
      const main = page.locator("main.sheet");
      await expect(main, `"${label}" rendered nothing`).not.toBeEmpty();
      await expect(
        page.locator("p.note.bad"),
        `"${label}" rendered an error`
      ).toHaveCount(0);
    }
  });

  test("the IFSCA page shows what the firm owes, with its figures", async ({
    page,
  }) => {
    await page.goto("/#/standing");

    await expect(page.getByRole("heading", { level: 1 })).toContainText(
      "Where you stand with IFSCA"
    );

    // Each of these is a section that existed as an API field for weeks
    // with nothing rendering it.
    for (const heading of [
      "Your registration",
      "Your customers, and when they are next reviewed",
      "Posts your licence requires",
      "What you owe IFSCA",
      "What IFSCA has actually acted on",
      "The rules this system enforces",
    ]) {
      await expect(
        page.getByRole("heading", { name: heading }),
        `the "${heading}" section is missing`
      ).toBeVisible();
    }
  });

  test("an unswept workspace says so above its own figures", async ({
    page,
  }) => {
    // The house rule, rendered. This workspace has never been swept -- the
    // test server runs without VINZOR_NIGHTLY -- so every count on the page
    // is a claim about records rather than about the world, and the page
    // has to say that before it says anything else.
    await page.goto("/#/standing");

    const swept = page.locator(".swept");
    await expect(swept).toBeVisible();
    await expect(swept).toContainText(
      "state of your records, not the state of the world"
    );

    // Above the figures, not buried under them.
    const sweptBox = await swept.boundingBox();
    const firstSection = await page
      .locator("main section")
      .first()
      .boundingBox();
    expect(
      sweptBox.y,
      "the staleness warning renders below the figures it qualifies"
    ).toBeLessThan(firstSection.y);
  });

  test("the uncategorised book is not reported as nothing overdue", async ({
    page,
  }) => {
    // The exact defect this figure was built to close: "no reviews
    // overdue" is true of a book nobody has categorised, and true in the
    // way that matters least. The caveat must travel with the count.
    await page.goto("/#/standing");

    const section = page
      .locator("section")
      .filter({ hasText: "Your customers, and when they are next reviewed" });

    await expect(section).toContainText("carry a risk category");
    await expect(
      section,
      "the count appears without the sentence explaining why nothing is overdue"
    ).toContainText("cannot appear as overdue");
  });

  test("the clause register opens and holds real clauses", async ({
    page,
  }) => {
    await page.goto("/#/standing");

    const rules = page.locator("#rules");
    await expect(rules).toBeHidden();

    await page.locator("#see-rules").click();
    await expect(rules).toBeVisible();

    // IFSCA's beneficial-ownership limb, at 10% rather than FATF's 25%.
    // If this row is gone, the register has lost the clause the product
    // is most specific about.
    await expect(rules).toContainText("1.3.3(a)");
    expect(await rules.locator("tbody tr").count()).toBeGreaterThan(20);
  });

  test("the queue lists real files, each identified", async ({ page }) => {
    // Each open file is an <li data-file="{case_id}">. Anchoring on that
    // rather than on "some link in main" -- the first version of this test
    // matched the hidden clause-register links left over from the previous
    // route and failed for a reason that had nothing to do with the queue.
    await page.goto("/#/queue");

    const files = page.locator("li[data-file]");
    await expect(files.first()).toBeVisible();
    expect(await files.count()).toBeGreaterThan(0);

    // A case id, not a blank card.
    const id = await files.first().getAttribute("data-file");
    expect(id, "a file in the queue carries no case id").toBeTruthy();
    await expect(page.locator("p.note.bad")).toHaveCount(0);
  });
});

test.describe("the shape of the page", () => {
  test("nothing scrolls sideways at a laptop width", async ({ page }) => {
    // An officer's daily driver. A page that scrolls horizontally is one
    // where a column of figures has silently gone off the edge.
    await page.setViewportSize({ width: 1280, height: 800 });
    await signIn(page);
    await page.goto("/#/standing");

    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth
    );
    expect(overflow, "the page scrolls sideways at 1280px").toBeLessThanOrEqual(
      1
    );
  });
});
