/**
 * Marine layer service — builds INCOIS WMS tile URLs for map toggles.
 * Each layer queries same coordinate resolver as OceanStateAgent (GPS > map > chat > PFZ).
 */

export type MarineLayer = 'sst' | 'wind' | 'current' | 'swell' | 'chlorophyll' | 'pfz';

const DELTA = 0.05;

function bbox(lon: number, lat: number): string {
  return `${lon-DELTA},${lat-DELTA},${lon+DELTA},${lat+DELTA}`;
}

function yyyymmdd(d: Date = new Date()): string {
  return d.toISOString().slice(0,10).replace(/-/g,'');
}

export function marineWmsUrl(layer: MarineLayer, lat: number, lon: number, date = new Date()): string {
  const bb = bbox(lon, lat);
  const ymd = yyyymmdd(date);
  const common = `SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&STYLES=&SRS=CRS:84&BBOX=${bb}&WIDTH=256&HEIGHT=256&FORMAT=image/png&TRANSPARENT=TRUE`;
  switch(layer){
    case 'sst':
      return `https://incois.gov.in/thredds/wms/osf/winds/SST_NIO_${ymd}.nc?${common}&LAYERS=SST`;
    case 'wind':
      return `https://incois.gov.in/thredds/wms/osf/ww3/rsmc_combined_ww3_${ymd}.nc?${common}&LAYERS=UWND:VWND-mag`;
    case 'current':
      return `https://incois.gov.in/thredds/wms/osf/currents/CURRENTS_NIO_${ymd}.nc?${common}&LAYERS=CURRENT`;
    case 'swell':
      return `https://incois.gov.in/thredds/wms/osf/ww3/rsmc_combined_ww3_${ymd}.nc?${common}&LAYERS=PHS01`;
    case 'chlorophyll':
      return `https://erddap.incois.gov.in/erddap/wms/incois_oceansat2_datasets/request?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&LAYERS=incois_oceansat2_datasets:CHL&STYLES=&CRS=CRS:84&BBOX=${bb}&WIDTH=256&HEIGHT=256&FORMAT=image/png&TRANSPARENT=TRUE`;
    case 'pfz':
      return `https://gemini.incois.gov.in/api/ws/pfzLines`;
    default: return '';
  }
}

export function resolveCoord(gps: [number,number]|null, mapPoint: [number,number]|null, chatPlace: [number,number]|null, pfzCoord: [number,number]|null): [number,number]|null {
  if (mapPoint) return mapPoint;
  if (gps) return gps;
  if (chatPlace) return chatPlace;
  if (pfzCoord) return pfzCoord;
  return null;
}
