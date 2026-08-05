import { describe, expect, it } from "vitest";

import { resolveDevAuthBypass } from "./devAuthBypass";

describe("resolveDevAuthBypass", () => {
  it("is off by default", () => {
    expect(resolveDevAuthBypass({})).toBe(false);
  });

  it("is off for any value other than 'true'", () => {
    expect(resolveDevAuthBypass({ DEV_AUTH_BYPASS: "false" })).toBe(false);
    expect(resolveDevAuthBypass({ DEV_AUTH_BYPASS: "1" })).toBe(false);
    expect(resolveDevAuthBypass({ DEV_AUTH_BYPASS: "" })).toBe(false);
  });

  it("activates in development (case-insensitive value, like the backend)", () => {
    expect(resolveDevAuthBypass({ DEV_AUTH_BYPASS: "true" })).toBe(true);
    expect(
      resolveDevAuthBypass({ DEV_AUTH_BYPASS: "TRUE", APP_ENV: "development" }),
    ).toBe(true);
  });

  it("throws instead of activating in production-like environments", () => {
    expect(() =>
      resolveDevAuthBypass({ DEV_AUTH_BYPASS: "true", APP_ENV: "production" }),
    ).toThrow(/forbidden/);
    expect(() =>
      resolveDevAuthBypass({ DEV_AUTH_BYPASS: "true", APP_ENV: "staging" }),
    ).toThrow(/forbidden/);
    expect(() =>
      resolveDevAuthBypass({ DEV_AUTH_BYPASS: "true", APP_ENV: "Production" }),
    ).toThrow(/forbidden/);
  });

  it("stays quiet in production when the bypass is not requested", () => {
    expect(resolveDevAuthBypass({ APP_ENV: "production" })).toBe(false);
    expect(
      resolveDevAuthBypass({ DEV_AUTH_BYPASS: "false", APP_ENV: "production" }),
    ).toBe(false);
  });
});
