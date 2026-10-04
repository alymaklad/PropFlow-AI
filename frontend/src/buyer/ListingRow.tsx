import type { Listing } from "../api";
import { DELIVERY, checkedLabel, formatPrice, listingTitle } from "../format";

type Props = { listing: Listing; onAsk: (listing: Listing) => void };

const capitalise = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

export function ListingRow({ listing, onAsk }: Props) {
  const facts = [
    listing.bathrooms ? `${listing.bathrooms} bathroom${listing.bathrooms === 1 ? "" : "s"}` : null,
    DELIVERY[listing.delivery_status],
  ].filter(Boolean).join(", ");
  const title = `${listingTitle(listing.bedrooms, listing.property_type)} in ${listing.location}`;
  return (
    <article className="listing" aria-labelledby={`l-${listing.listing_id}`}>
      <img className="listing-photo" src={listing.photo} alt="" width={1200} height={800}
        loading="lazy" decoding="async" />
      <div className="listing-body">
        <p className="listing-price num">{formatPrice(listing.price, listing.currency)}</p>
        <h3 id={`l-${listing.listing_id}`}>{title}</h3>
        <p className="listing-facts">
          {facts}
          {listing.amenities.length > 0 && (
            <span className="listing-amenities">{capitalise(listing.amenities.join(", "))}</span>
          )}
        </p>
        {listing.description && <p className="listing-desc">{listing.description}</p>}
        <button type="button" className="btn btn-quiet listing-ask" onClick={() => onAsk(listing)}>
          Ask about this home
        </button>
      </div>
      <div className="seal" title="Availability and price confirmed with the owner or developer">
        <span className="seal-text">{checkedLabel(listing.verified_days_ago)}</span>
        <span className="seal-id">{listing.listing_id}</span>
      </div>
    </article>
  );
}
