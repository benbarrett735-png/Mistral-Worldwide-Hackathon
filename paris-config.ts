/**
 * Paris-specific configuration for Helpstroll/Flystroll demo
 * Map center, drone station, demo route waypoints
 *
 * Flow: User pre-inputs walking route → Flystroll uses 3D city map
 * to generate drone flight path → in-flight cameras + lidar handle
 * obstacles and route deviations.
 */

export const PARIS = {
  /** Map center - Île de la Cité / Notre-Dame area */
  center: [2.3522, 48.8566] as [number, number],
  defaultZoom: 15,

  /** Drone station - e.g. near Gare du Nord for demo */
  droneStation: {
    coords: [2.3553, 48.8809] as [number, number],
    label: "Drone Station - Gare du Nord",
  },

  /** Demo route: user walks this path (lat, lng pairs) */
  demoRoute: [
    [2.3553, 48.8809], // Start: Gare du Nord
    [2.3565, 48.8795], // Rue de Dunkerque
    [2.3580, 48.8780], // Rue La Fayette
    [2.3600, 48.8765], // End point
  ] as [number, number][],

  /** Approximate Paris city bounds for map fit */
  bounds: [
    [2.22, 48.8],   // SW
    [2.47, 48.92],  // NE
  ] as [[number, number], [number, number]],
};
