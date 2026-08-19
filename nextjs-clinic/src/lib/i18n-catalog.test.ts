import { describe, expect, it } from "vitest";

import he from "@/messages/he.json";
import en from "@/messages/en.json";

describe("i18n catalogs", () => {
  it("he and en catalogs have the same keys", () => {
    const heKeys = Object.keys(he).sort();
    const enKeys = Object.keys(en).sort();
    expect(enKeys).toEqual(heKeys);
  });

  it("has a non-trivial number of translation keys", () => {
    expect(Object.keys(he).length).toBeGreaterThan(500);
  });
});

