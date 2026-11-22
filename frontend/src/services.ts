import type { ServiceIconName } from './components/Icons'

// Friendly names, clinical icons, and groups for the 16 Care Finder services (keys match src/hc/care.py).
export interface ServiceInfo {
  icon: ServiceIconName
  name: string
  hint: string
  group: string
  featured?: boolean
}

export const SERVICE_INFO: Record<string, ServiceInfo> = {
  dialysis: { icon: 'kidney', name: 'Kidney dialysis', hint: 'Haemodialysis · 2–3×/wk', group: 'Ongoing care', featured: true },
  emergency_c_section: { icon: 'maternity', name: 'Emergency C-section', hint: 'High-risk delivery · LSCS', group: 'Mother & baby', featured: true },
  emergency_department: { icon: 'activity', name: 'Emergency room', hint: '24-hour casualty / ER', group: 'Urgent', featured: true },
  nicu: { icon: 'baby', name: 'Newborn ICU', hint: 'NICU · neonatal care', group: 'Mother & baby', featured: true },
  cardiac_cath: { icon: 'heart', name: 'Heart angioplasty', hint: 'Cardiac cath lab', group: 'Heart & surgery', featured: true },
  mri: { icon: 'scan', name: 'MRI scan', hint: 'Diagnostic imaging', group: 'Diagnostics', featured: true },

  trauma_care: { icon: 'ambulance', name: 'Accident & trauma', hint: 'Trauma centre', group: 'Urgent' },
  burn_care: { icon: 'flame', name: 'Burn unit', hint: 'Specialized burns care', group: 'Urgent' },
  icu: { icon: 'bed', name: 'Intensive care', hint: 'Adult ICU / critical care', group: 'Urgent' },
  maternity_delivery: { icon: 'baby', name: 'Maternity delivery', hint: 'Normal obstetric delivery', group: 'Mother & baby' },
  blood_bank: { icon: 'droplet', name: 'Blood bank', hint: 'Blood & transfusion', group: 'Mother & baby' },
  chemotherapy: { icon: 'pill', name: 'Chemotherapy', hint: 'Medical oncology', group: 'Ongoing care' },
  radiotherapy: { icon: 'radiation', name: 'Radiotherapy', hint: 'Radiation oncology', group: 'Ongoing care' },
  cardiac_surgery: { icon: 'heart', name: 'Cardiac surgery', hint: 'Bypass & valve surgery', group: 'Heart & surgery' },
  cataract_surgery: { icon: 'eye', name: 'Cataract surgery', hint: 'Ophthalmic surgery', group: 'Heart & surgery' },
  ct_scan: { icon: 'scan', name: 'CT scan', hint: 'Diagnostic imaging', group: 'Diagnostics' },
}

export const FEATURED_SERVICE_KEYS = [
  'dialysis',
  'emergency_c_section',
  'emergency_department',
  'nicu',
  'cardiac_cath',
  'mri',
]

export const GROUP_ORDER = ['Urgent', 'Mother & baby', 'Ongoing care', 'Heart & surgery', 'Diagnostics']

export const serviceName = (key: string, fallback = key) => SERVICE_INFO[key]?.name ?? fallback
export const serviceIcon = (key: string): ServiceIconName => SERVICE_INFO[key]?.icon ?? 'activity'
