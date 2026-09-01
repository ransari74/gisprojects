/**
 * A small fixed icon set, inline SVG rather than an icon-font dependency.
 *
 * Every path uses `stroke="currentColor"` and no fill, so an icon always
 * matches whatever text color it sits beside -- including a NavLink's active
 * state, which is set via a CSS class this component never sees. That is also
 * why these are React components and not an <img>/sprite sheet: currentColor
 * doesn't work across those without extra plumbing, and every one of these
 * icons is a UI glyph next to text, never artwork in its own right.
 *
 * The set matches the icon names the backend already assigns per project
 * (`app/services/layers.py`'s PROJECTS dict) plus the handful the map's own
 * floating controls need. Adding a project means adding one name here.
 */

import type { SVGProps } from 'react';

export type IconName =
  | 'sprout'
  | 'map'
  | 'users'
  | 'route'
  | 'mountain'
  | 'satellite'
  | 'layers'
  | 'road'
  | 'image'
  | 'close'
  | 'shield';

interface IconProps extends Omit<SVGProps<SVGSVGElement>, 'name'> {
  name: IconName;
  size?: number;
}

const PATHS: Record<IconName, JSX.Element> = {
  sprout: (
    <>
      <path d="M7 20h10" />
      <path d="M12 20v-8" />
      <path d="M12 12c0-3.5-2.5-6-7-6 0 3.9 2.7 6 7 6Z" />
      <path d="M12 9c0-3 2-5 6-5 0 3.3-2.2 5-6 5Z" />
    </>
  ),
  map: (
    <>
      <path d="M9 4 3.5 6v14L9 18l6 2 5.5-2V4L15 6 9 4Z" />
      <path d="M9 4v14" />
      <path d="M15 6v14" />
    </>
  ),
  users: (
    <>
      <circle cx="9" cy="8" r="3" />
      <path d="M3.5 20c0-3.6 2.5-6 5.5-6s5.5 2.4 5.5 6" />
      <circle cx="17" cy="9" r="2.4" />
      <path d="M15.8 14.2c2.4.3 4.2 2.4 4.2 5.3" />
    </>
  ),
  route: (
    <>
      <circle cx="5.5" cy="6.5" r="2" />
      <circle cx="18.5" cy="17.5" r="2" />
      <path d="M5.5 8.5v3a3 3 0 0 0 3 3h7a3 3 0 0 1 3 3" />
    </>
  ),
  mountain: (
    <>
      <path d="M3 19 9.5 8l3.2 5.2L15 10l6 9H3Z" />
      <path d="M9.5 8 11 10.5" />
    </>
  ),
  satellite: (
    // A globe with a tilted orbit ring and a satellite riding it -- reads as
    // "orbit" at a glance, unlike the diagonal-burst design this replaced,
    // which compressed into an asterisk at nav-bar size.
    <>
      <circle cx="10" cy="13.5" r="4" />
      <ellipse cx="10" cy="13.5" rx="8.6" ry="3.1" transform="rotate(-18 10 13.5)" />
      <circle cx="18.7" cy="8.4" r="1.3" fill="currentColor" stroke="none" />
    </>
  ),
  layers: (
    <>
      <path d="m12 3 8.5 4.5L12 12 3.5 7.5 12 3Z" />
      <path d="m3.5 12 8.5 4.5 8.5-4.5" />
      <path d="m3.5 16.5 8.5 4.5 8.5-4.5" />
    </>
  ),
  road: (
    <>
      <path d="M9 4 5 20" />
      <path d="M15 4l4 16" />
      <path d="M11.3 9h1.4M10.6 13h2.8" />
    </>
  ),
  image: (
    <>
      <rect x="3.5" y="4.5" width="17" height="15" rx="1.5" />
      <circle cx="8.5" cy="9.5" r="1.6" />
      <path d="m5 17 4.5-5 3.5 3.8 2.5-2.8L20.5 17" />
    </>
  ),
  close: (
    <>
      <path d="m6 6 12 12" />
      <path d="m18 6-12 12" />
    </>
  ),
  shield: (
    <>
      <path d="M12 3.5 19 6v6c0 4.4-3 7.7-7 8.5-4-.8-7-4.1-7-8.5V6l7-2.5Z" />
      <path d="m9 12 2.2 2.2L15.5 10" />
    </>
  ),
};

export function Icon({ name, size = 16, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {PATHS[name]}
    </svg>
  );
}
