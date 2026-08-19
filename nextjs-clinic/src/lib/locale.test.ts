import { describe, expect, it } from "vitest";

import { localeToDir, otherLocale } from "./locale";

describe("locale helpers", () => {
  it("maps he to rtl", () => {
    expect(localeToDir("he")).toBe("rtl");
  });

  it("maps en to ltr", () => {
    expect(localeToDir("en")).toBe("ltr");
  });

  it("toggles between he and en", () => {
    expect(otherLocale("he")).toBe("en");
    expect(otherLocale("en")).toBe("he");
  });
});

