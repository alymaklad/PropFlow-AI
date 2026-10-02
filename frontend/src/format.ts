// Formatting shared by the buyer site and the dashboard.

const VOWELS = /^[aeiou]/i;

export function article(word: string): "a" | "an" {
  return VOWELS.test(word) ? "an" : "a";
}

export function formatPrice(price: number, currency: string): string {
  if (price >= 1_000_000) {
    const millions = (price / 1_000_000).toFixed(2).replace(/\.?0+$/, "");
    return `${millions} million ${currency}`;
  }
  return `${Math.round(price).toLocaleString("en-US")} ${currency}`;
}

export function typeName(type: string): string {
  return type === "commercial" ? "shop" : type;
}

export function bedroomsLabel(bedrooms: number | null, type: string): string | null {
  if (type === "studio" || bedrooms === 0) return null;
  if (bedrooms === null) return null;
  return `${bedrooms}-bedroom`;
}

export function listingTitle(bedrooms: number | null, type: string): string {
  const size = bedroomsLabel(bedrooms, type);
  const name = typeName(type);
  const text = size ? `${size} ${name}` : name;
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export const DELIVERY: Record<string, string> = {
  ready: "Ready to move in",
  under_construction: "Under construction",
  off_plan: "Off plan",
};

export function checkedLabel(days: number): string {
  if (days <= 0) return "Checked today";
  if (days === 1) return "Checked yesterday";
  return `Checked ${days} days ago`;
}

export function percent(numerator: number, denominator: number): string {
  if (!denominator) return "none yet";
  return `${((numerator / denominator) * 100).toFixed(1)}%`;
}

export function when(iso: string): string {
  const date = new Date(iso);
  return date.toLocaleString("en-GB", {
    weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

export function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`;
}
