import type { LucideIcon } from "lucide-react";
import {
  DollarSign,
  FileText,
  Hammer,
  Pipette,
  Trash2,
  Wrench,
  Zap,
} from "lucide-react";

export const SOURCE_LABELS: Record<string, string> = {
  naip: "NAIP",
  landsat: "Landsat",
  sentinel2: "Sentinel-2",
  usgs_topo: "USGS Topo",
  census: "Census",
  property: "Property",
};

export interface EventTypeConfig {
  label: string;
  color: string;
  icon: LucideIcon;
}

export const EVENT_TYPE_CONFIG: Record<string, EventTypeConfig> = {
  sale: {
    label: "Sale",
    color: "bg-amber-500 text-amber-50",
    icon: DollarSign,
  },
  permit_building: {
    label: "Building",
    color: "bg-orange-600 text-orange-50",
    icon: Hammer,
  },
  permit_demolition: {
    label: "Demolition",
    color: "bg-red-600 text-red-50",
    icon: Trash2,
  },
  permit_electrical: {
    label: "Electrical",
    color: "bg-yellow-600 text-yellow-50",
    icon: Zap,
  },
  permit_mechanical: {
    label: "Mechanical",
    color: "bg-slate-600 text-slate-50",
    icon: Wrench,
  },
  permit_plumbing: {
    label: "Plumbing",
    color: "bg-sky-600 text-sky-50",
    icon: Pipette,
  },
  permit_other: {
    label: "Permit",
    color: "bg-slate-600 text-slate-50",
    icon: FileText,
  },
  zoning_change: {
    label: "Zoning",
    color: "bg-purple-600 text-purple-50",
    icon: FileText,
  },
  assessment: {
    label: "Assessment",
    color: "bg-teal-600 text-teal-50",
    icon: FileText,
  },
};
