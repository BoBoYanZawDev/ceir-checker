import type { ImeiPair } from "./types";

export function parseImeiText(input: string): ImeiPair[] {
  return input
    .split(/\r?\n/)
    .map((line) => line.replace(/#.*$/, "").trim())
    .filter(Boolean)
    .map((line) => line.split(/[\s,;|]+/).filter(Boolean))
    .filter((values) => values.length > 0)
    .map(([imei1, imei2 = ""]) => ({ imei1, imei2 }));
}

export function isValidImei(value: string): boolean {
  if (!/^\d{15}$/.test(value)) return false;
  const sum = value
    .split("")
    .map(Number)
    .reduce((total, digit, index) => {
      const doubled = index % 2 === 1 ? digit * 2 : digit;
      return total + (doubled > 9 ? doubled - 9 : doubled);
    }, 0);
  return sum % 10 === 0;
}

export function formatCurrency(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}
