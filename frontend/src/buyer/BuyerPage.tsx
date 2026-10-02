import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { type Listing, type ListingsResponse, getListings } from "../api";
import { plural } from "../format";
import { InquiryForm } from "./InquiryForm";
import { ListingRow } from "./ListingRow";
import { EMPTY_SEARCH, type Search, SentenceBuilder } from "./SentenceBuilder";
import "./buyer.css";

export function BuyerPage() {
  const [search, setSearch] = useState<Search>(EMPTY_SEARCH);
  const [data, setData] = useState<ListingsResponse | null>(null);
  const [options, setOptions] = useState<{ types: string[]; locations: string[] }>({ types: [], locations: [] });
  const [loadError, setLoadError] = useState(false);
  const [message, setMessage] = useState("");
  const formRef = useRef<HTMLElement>(null);

  const filters = useMemo(() => ({
    property_type: search.type !== "any" ? search.type : undefined,
    location: search.location !== "any" ? search.location : undefined,
    bedrooms: search.bedrooms !== "any" ? Number(search.bedrooms) : undefined,
    budget_max: search.budget !== "any" ? Number(search.budget) : undefined,
  }), [search]);

  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      getListings(filters, controller.signal)
        .then((response) => {
          setData(response);
          setLoadError(false);
          setOptions((current) => current.types.length ? current
            : { types: response.property_types, locations: response.locations });
        })
        .catch((error) => { if (error.name !== "AbortError") setLoadError(true); });
    }, 150);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [filters]);

  function ask(listing?: Listing) {
    if (listing) setMessage(`I'm interested in ${listing.listing_id}. `);
    formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    formRef.current?.querySelector<HTMLInputElement>("#f-name")?.focus({ preventScroll: true });
  }

  const count = data?.listings.length ?? 0;

  return (
    <div className="buyer">
      <header className="site-header">
        <Link to="/" className="wordmark">PropFlow Homes</Link>
        <nav aria-label="Main">
          <a href="#homes">Homes</a>
          <a href="#ask">Ask an advisor</a>
          <Link to="/staff">Staff</Link>
        </nav>
      </header>

      <main>
        <section className="hero" aria-label="Search">
          <SentenceBuilder search={search} types={options.types} locations={options.locations} onChange={setSearch} />
          <div className="hero-foot">
            <p className="match-line" aria-live="polite">
              {loadError ? "Listings are unavailable right now. Try again in a moment."
                : data === null ? "Finding homes..."
                : count === 0 ? "Nothing matches yet. Change a word above, or send us your search and an advisor will look for you."
                : `${plural(count, "home")} ${count === 1 ? "matches" : "match"}, each checked with its owner or developer in the last ${data.freshness_days} days.`}
            </p>
            <div className="hero-actions">
              <button type="button" className="btn" onClick={() => ask()}>Send this search to an advisor</button>
              {JSON.stringify(search) !== JSON.stringify(EMPTY_SEARCH) && (
                <button type="button" className="btn btn-quiet" onClick={() => setSearch(EMPTY_SEARCH)}>Clear search</button>
              )}
            </div>
          </div>
        </section>

        <section id="homes" className="listings" aria-label="Homes">
          {data?.listings.map((listing) => <ListingRow key={listing.listing_id} listing={listing} onAsk={ask} />)}
        </section>

        <section id="ask" className="ask" ref={formRef} aria-labelledby="ask-title">
          <div className="ask-intro">
            <h2 id="ask-title">Tell an advisor what you need</h2>
            <p>
              A real person reads every inquiry. If we have matching homes you get them by email right away;
              if not, your advisor looks further and gets back to you.
            </p>
          </div>
          <InquiryForm search={search} message={message} onMessageChange={setMessage} />
        </section>
      </main>

      <footer className="site-footer">
        <p>
          Listings are confirmed with the owner or developer at least every two weeks. Prices and
          availability can still change; your advisor confirms them before any viewing.
        </p>
      </footer>
    </div>
  );
}
