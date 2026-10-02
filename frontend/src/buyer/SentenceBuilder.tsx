import { article, formatPrice, typeName } from "../format";

export type Search = {
  type: string; // "any" or a property type
  bedrooms: string; // "any" or "1".."5"
  location: string; // "any" or a location
  budget: string; // "any" or a maximum in EGP
};

export const EMPTY_SEARCH: Search = { type: "any", bedrooms: "any", location: "any", budget: "any" };

const BUDGETS = [3, 5, 8, 10, 15, 20, 30].map((m) => m * 1_000_000);
const BEDROOMS = ["1", "2", "3", "4", "5"];

type ChoiceProps = {
  label: string;
  value: string;
  options: { value: string; text: string }[];
  onChange: (value: string) => void;
};

// A word in the sentence that is really a <select>: the visible text sets the width, the
// transparent native select on top handles input, so it stays keyboard and screen-reader friendly.
function Choice({ label, value, options, onChange }: ChoiceProps) {
  const current = options.find((o) => o.value === value)?.text ?? options[0].text;
  return (
    <span className="choice">
      <span className="choice-text" aria-hidden="true">{current}</span>
      <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.text}</option>
        ))}
      </select>
    </span>
  );
}

type Props = {
  search: Search;
  types: string[];
  locations: string[];
  onChange: (search: Search) => void;
};

export function SentenceBuilder({ search, types, locations, onChange }: Props) {
  const set = (key: keyof Search) => (value: string) => {
    const next = { ...search, [key]: value };
    if (key === "type" && value === "studio") next.bedrooms = "any";
    onChange(next);
  };
  const typeWord = search.type === "any" ? "home" : typeName(search.type);
  const showSize = search.type !== "studio" && search.type !== "land";

  return (
    <h1 className="sentence">
      I'm looking for {article(typeWord)}{" "}
      <Choice
        label="Property type"
        value={search.type}
        onChange={set("type")}
        options={[{ value: "any", text: "home" }, ...types.map((t) => ({ value: t, text: typeName(t) }))]}
      />
      {showSize && (
        <>
          {" "}
          <Choice
            label="Bedrooms"
            value={search.bedrooms}
            onChange={set("bedrooms")}
            options={[
              { value: "any", text: "of any size" },
              ...BEDROOMS.map((b) => ({ value: b, text: `with ${b} bedroom${b === "1" ? "" : "s"}` })),
            ]}
          />
        </>
      )}{" "}
      <Choice
        label="Area"
        value={search.location}
        onChange={set("location")}
        options={[{ value: "any", text: "anywhere" }, ...locations.map((l) => ({ value: l, text: `in ${l}` }))]}
      />{" "}
      <Choice
        label="Budget"
        value={search.budget}
        onChange={set("budget")}
        options={[
          { value: "any", text: "at any price" },
          ...BUDGETS.map((b) => ({ value: String(b), text: `for up to ${formatPrice(b, "EGP")}` })),
        ]}
      />
      .
    </h1>
  );
}

export function describeSearch(search: Search): string {
  const parts: string[] = [];
  if (search.bedrooms !== "any") parts.push(`${search.bedrooms}-bedroom`);
  parts.push(search.type === "any" ? "home" : typeName(search.type));
  let text = parts.join(" ");
  if (search.location !== "any") text += ` in ${search.location}`;
  if (search.budget !== "any") text += `, up to ${formatPrice(Number(search.budget), "EGP")}`;
  return text;
}
