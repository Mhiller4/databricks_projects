// Friendly names, icons and groups for the 16 Care Finder services (keys match src/hc/care.py).
export interface ServiceInfo { icon: string; name: string; hint: string; group: string }

export const SERVICE_INFO: Record<string, ServiceInfo> = {
  emergency_department: { icon: '🚨', name: 'Emergency room', hint: 'Open 24 hours', group: 'Urgent' },
  trauma_care: { icon: '🚑', name: 'Accident / injury', hint: 'Trauma care', group: 'Urgent' },
  burn_care: { icon: '🔥', name: 'Burns', hint: 'Burn unit', group: 'Urgent' },
  icu: { icon: '🛏️', name: 'Intensive care', hint: 'ICU', group: 'Urgent' },
  emergency_c_section: { icon: '🤰', name: 'Emergency C-section', hint: 'High-risk delivery', group: 'Mother & baby' },
  maternity_delivery: { icon: '👶', name: 'Giving birth', hint: 'Normal delivery', group: 'Mother & baby' },
  nicu: { icon: '🍼', name: 'Newborn intensive care', hint: 'NICU', group: 'Mother & baby' },
  blood_bank: { icon: '🩸', name: 'Blood / transfusion', hint: 'Blood bank', group: 'Mother & baby' },
  dialysis: { icon: '🫘', name: 'Kidney dialysis', hint: '2–3 times a week', group: 'Ongoing care' },
  chemotherapy: { icon: '💊', name: 'Cancer chemotherapy', hint: 'Oncology', group: 'Ongoing care' },
  radiotherapy: { icon: '☢️', name: 'Radiotherapy', hint: 'Cancer radiation', group: 'Ongoing care' },
  cardiac_cath: { icon: '💓', name: 'Heart: angioplasty', hint: 'Cath lab', group: 'Heart & surgery' },
  cardiac_surgery: { icon: '❤️', name: 'Heart surgery', hint: 'Bypass, valves', group: 'Heart & surgery' },
  cataract_surgery: { icon: '👁️', name: 'Cataract surgery', hint: 'Eye operation', group: 'Heart & surgery' },
  mri: { icon: '🧲', name: 'MRI scan', hint: 'Imaging', group: 'Scans' },
  ct_scan: { icon: '🩻', name: 'CT scan', hint: 'Imaging', group: 'Scans' },
}

export const GROUP_ORDER = ['Urgent', 'Mother & baby', 'Ongoing care', 'Heart & surgery', 'Scans']

export const serviceName = (key: string, fallback = key) => SERVICE_INFO[key]?.name ?? fallback
