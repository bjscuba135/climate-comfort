// Climate Comfort card — moved.
//
// From integration 2.0 the card ships inside the integration and is loaded
// automatically, so this dashboard resource is no longer needed and can be
// removed (Settings → Dashboards → Resources). Until then, this file hands
// over to the copy your Home Assistant serves.
import('/comfort_climate/climate-comfort-card.js').catch((err) => {
  console.warn('Climate Comfort card: update the integration to 2.0 or newer.', err);
});
