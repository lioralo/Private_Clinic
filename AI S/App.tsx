import React, { useState } from 'react';
import { 
  LayoutDashboard, 
  Users, 
  Calendar as CalendarIcon, 
  Settings, 
  HelpCircle, 
  UserPlus, 
  LogOut, 
  Search, 
  Bell, 
  Globe, 
  ChevronRight, 
  MoreVertical, 
  History, 
  FileText, 
  Stethoscope, 
  Archive, 
  Clock, 
  MessageSquare, 
  ShieldCheck, 
  BellRing, 
  Trash2, 
  Camera, 
  Mail, 
  Phone, 
  MapPin, 
  ArrowRight, 
  CheckCircle2, 
  Info,
  ChevronLeft,
  ChevronDown,
  Filter,
  ArrowUpDown,
  Eye,
  Edit2,
  Lock,
  Smartphone,
  AlertCircle
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { cn } from './lib/utils';

// --- Types ---
type Screen = 'dashboard' | 'settings' | 'groups' | 'calendar' | 'add-patient' | 'patients' | 'help';

// --- Components ---

const Sidebar = ({ activeScreen, setScreen }: { activeScreen: Screen, setScreen: (s: Screen) => void }) => {
  const menuItems = [
    { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { id: 'patients', label: 'Patients', icon: Users },
    { id: 'calendar', label: 'Calendar', icon: CalendarIcon },
    { id: 'groups', label: 'Groups', icon: Users }, // Using Users for Groups as well
    { id: 'help', label: 'Support', icon: HelpCircle },
  ];

  return (
    <aside className="fixed left-0 top-0 h-screen w-64 bg-slate-50 border-r border-slate-200 flex flex-col p-4 z-40">
      <div className="flex items-center gap-3 mb-8 px-2">
        <div className="w-10 h-10 rounded-lg bg-primary flex items-center justify-center text-white">
          <Stethoscope size={24} />
        </div>
        <div>
          <h1 className="font-black text-teal-950 leading-none text-lg">Sanctuary CRM</h1>
          <p className="text-[10px] text-slate-500 uppercase tracking-widest mt-1">Medical Admin</p>
        </div>
      </div>

      <nav className="flex-1 space-y-1">
        {menuItems.map((item) => (
          <button
            key={item.id}
            onClick={() => setScreen(item.id as Screen)}
            className={cn(
              "w-full flex items-center gap-3 px-4 py-3 rounded-lg transition-all duration-200 text-sm font-medium",
              activeScreen === item.id 
                ? "bg-primary/10 text-primary" 
                : "text-slate-600 hover:bg-slate-200"
            )}
          >
            <item.icon size={18} />
            <span>{item.label}</span>
          </button>
        ))}
      </nav>

      <div className="mt-4 mb-6">
        <button 
          onClick={() => setScreen('add-patient')}
          className="w-full bg-primary text-white py-3 px-4 rounded-lg font-bold flex items-center justify-center gap-2 shadow-md hover:opacity-90 transition-opacity"
        >
          <UserPlus size={18} />
          New Patient
        </button>
      </div>

      <div className="mt-auto border-t border-slate-200 pt-4 space-y-1">
        <button 
          onClick={() => setScreen('settings')}
          className={cn(
            "w-full flex items-center gap-3 px-4 py-3 rounded-lg transition-all duration-200 text-sm font-medium",
            activeScreen === 'settings' ? "bg-primary/10 text-primary" : "text-slate-600 hover:bg-slate-200"
          )}
        >
          <Settings size={18} />
          <span>Settings</span>
        </button>
        <button className="w-full flex items-center gap-3 px-4 py-3 text-slate-600 hover:bg-slate-200 rounded-lg transition-all duration-200 text-sm font-medium">
          <LogOut size={18} />
          <span>Logout</span>
        </button>
      </div>
    </aside>
  );
};

const TopNav = ({ title }: { title: string }) => {
  return (
    <header className="fixed top-0 right-0 left-64 bg-white/85 backdrop-blur-md z-30 flex justify-between items-center px-8 py-4 shadow-sm border-b border-slate-200">
      <div className="flex items-center gap-6">
        <h2 className="text-xl font-bold text-teal-900 tracking-tight">{title}</h2>
        <div className="flex items-center bg-slate-100 rounded-full px-4 py-2 w-96">
          <Search size={18} className="text-slate-400 mr-2" />
          <input 
            className="bg-transparent border-none focus:ring-0 text-sm w-full placeholder:text-slate-400" 
            placeholder="Search records..." 
            type="text" 
          />
        </div>
      </div>
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-1">
          <button className="p-2 text-slate-500 hover:text-primary transition-colors">
            <Globe size={20} />
          </button>
          <button className="p-2 text-slate-500 hover:text-primary transition-colors relative">
            <Bell size={20} />
            <span className="absolute top-2 right-2 w-2 h-2 bg-red-500 rounded-full border-2 border-white"></span>
          </button>
        </div>
        <div className="h-8 w-[1px] bg-slate-200 mx-2"></div>
        <div className="flex items-center gap-3">
          <div className="text-right">
            <p className="text-sm font-bold text-teal-900 leading-none">Dr. Julian Vance</p>
            <p className="text-[10px] text-slate-500 font-medium">Chief Resident</p>
          </div>
          <img 
            alt="Physician Profile" 
            className="w-10 h-10 rounded-full border-2 border-primary shadow-sm object-cover" 
            src="https://picsum.photos/seed/doctor/100/100"
            referrerPolicy="no-referrer"
          />
        </div>
      </div>
    </header>
  );
};

// --- Screens ---

const Dashboard = () => {
  const [openSections, setOpenSections] = useState({
    caseload: true,
    candidates: true,
    insights: true,
  });

  const stats = [
    { label: 'Ongoing', value: '11', change: null, color: 'text-primary' },
    { label: 'Candidate', value: '04', change: null, color: 'text-primary' },
    { label: 'Archived', value: '11', change: null, color: 'text-primary' },
  ];

  const patients = [
    { name: 'Eleanor Vance', therapy: 'Psychodynamic Therapy', status: 'Ongoing', lastSession: '2d ago', image: 'https://picsum.photos/seed/eleanor/100/100' },
    { name: 'Marcus Thorne', therapy: 'Private Consultation', status: 'Ongoing', nextSession: 'Today, 14:00', image: 'https://picsum.photos/seed/marcus/100/100' },
    { name: 'Sienna Brooks', therapy: 'Behavioral Therapy', status: 'Archived', completed: 'Oct 2023', image: 'https://picsum.photos/seed/sienna/100/100' },
    { name: 'David Chen', therapy: 'Initial Assessment', status: 'Candidate', assigned: '1h ago', image: 'https://picsum.photos/seed/david/100/100' },
  ];

  const toggleSection = (key: keyof typeof openSections) => {
    setOpenSections((current) => ({ ...current, [key]: !current[key] }));
  };

  return (
    <div className="space-y-10">
      <section>
        <h1 className="text-4xl font-extrabold text-primary tracking-tight mb-2">Welcome back, Dr. Julian.</h1>
        <p className="text-secondary text-lg font-medium opacity-80">You have 12 appointments scheduled for today across 3 locations.</p>
      </section>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {stats.map((stat, i) => (
          <motion.div 
            key={i}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.1 }}
            className="bg-white p-5 rounded-xl shadow-sm border border-slate-100 max-w-sm"
          >
            <span className="text-secondary font-semibold text-sm uppercase tracking-wider">{stat.label}</span>
            <div className="flex items-baseline gap-2 mt-1">
              <span className={cn("text-4xl font-bold tracking-tighter", stat.color)}>{stat.value}</span>
              {stat.change && (
                <span className="text-teal-600 text-xs font-bold bg-teal-50 px-2 py-0.5 rounded-full">{stat.change}</span>
              )}
            </div>
          </motion.div>
        ))}
      </div>

      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="relative w-full md:w-96 group">
          <Search size={18} className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-400 group-focus-within:text-primary transition-colors" />
          <input 
            className="w-full pl-12 pr-4 py-3 bg-slate-100 border-none rounded-lg focus:ring-2 focus:ring-primary/20 focus:bg-white transition-all placeholder:text-slate-400" 
            placeholder="Search patients..." 
            type="text" 
          />
        </div>
        <div className="flex items-center gap-3">
          <button className="flex items-center gap-2 bg-slate-100 px-4 py-3 rounded-lg hover:bg-slate-200 transition-colors text-slate-600 font-medium text-sm">
            <Filter size={16} />
            Filter
          </button>
          <button className="flex items-center gap-2 bg-slate-100 px-4 py-3 rounded-lg hover:bg-slate-200 transition-colors text-slate-600 font-medium text-sm">
            <ArrowUpDown size={16} />
            Sort
          </button>
        </div>
      </div>

      <div className="space-y-4">
        <section className="bg-white rounded-xl border border-slate-100 shadow-sm overflow-hidden">
          <button onClick={() => toggleSection('caseload')} className="w-full px-5 py-4 flex items-center justify-between text-left">
            <div>
              <h2 className="text-lg font-bold text-primary">Caseload Snapshot</h2>
              <p className="text-sm text-slate-500">Current active and recently changed cases.</p>
            </div>
            <ChevronDown className={cn('text-slate-400 transition-transform', !openSections.caseload && '-rotate-90')} size={18} />
          </button>
          {openSections.caseload && (
            <div className="px-5 pb-5 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {patients.slice(0, 3).map((patient, i) => (
                <motion.div 
                  key={i}
                  initial={{ opacity: 0, scale: 0.95 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ delay: 0.35 + i * 0.08 }}
                  className={cn(
                    'bg-slate-50 rounded-xl overflow-hidden transition-all group cursor-pointer border border-slate-100',
                    patient.status === 'Archived' && 'opacity-70'
                  )}
                >
                  <div className={cn('h-2 w-full', patient.status === 'Archived' ? 'bg-slate-300' : 'bg-primary')} />
                  <div className="p-5">
                    <div className="flex justify-between items-start mb-4 gap-3">
                      <img src={patient.image} alt={patient.name} className="w-12 h-12 rounded-lg object-cover" referrerPolicy="no-referrer" />
                      <span className={cn(
                        'px-3 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider border',
                        patient.status === 'Ongoing' ? 'bg-teal-50 text-teal-800 border-teal-100' :
                        patient.status === 'Candidate' ? 'bg-amber-50 text-amber-800 border-amber-100' :
                        'bg-slate-50 text-slate-600 border-slate-200'
                      )}>
                        {patient.status}
                      </span>
                    </div>
                    <h3 className="text-lg font-bold text-primary mb-1">{patient.name}</h3>
                    <p className="text-secondary text-sm font-medium mb-5">{patient.therapy}</p>
                    <div className="flex items-center justify-between pt-4 border-t border-slate-100">
                      <div className="flex gap-2">
                        {patient.status === 'Ongoing' && <History size={16} className="text-slate-400" />}
                        {patient.status === 'Ongoing' && <FileText size={16} className="text-slate-400" />}
                        {patient.status === 'Archived' && <Archive size={16} className="text-slate-400" />}
                        {patient.status === 'Candidate' && <Clock size={16} className="text-slate-400" />}
                      </div>
                      <span className="text-xs text-slate-400 font-medium">{patient.lastSession || patient.nextSession || patient.completed || patient.assigned}</span>
                    </div>
                  </div>
                </motion.div>
              ))}
            </div>
          )}
        </section>

        <section className="bg-white rounded-xl border border-slate-100 shadow-sm overflow-hidden">
          <button onClick={() => toggleSection('candidates')} className="w-full px-5 py-4 flex items-center justify-between text-left">
            <div>
              <h2 className="text-lg font-bold text-primary">Candidate Queue</h2>
              <p className="text-sm text-slate-500">People still awaiting the next clinical decision.</p>
            </div>
            <ChevronDown className={cn('text-slate-400 transition-transform', !openSections.candidates && '-rotate-90')} size={18} />
          </button>
          {openSections.candidates && (
            <div className="px-5 pb-5">
              {patients.filter((patient) => patient.status === 'Candidate').map((patient) => (
                <div key={patient.name} className="flex items-center justify-between gap-4 rounded-xl border border-amber-100 bg-amber-50/70 px-4 py-3">
                  <div>
                    <div className="font-semibold text-slate-900">{patient.name}</div>
                    <div className="text-sm text-slate-500">{patient.therapy}</div>
                  </div>
                  <span className="text-xs font-semibold text-amber-700">{patient.assigned}</span>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="bg-primary text-white rounded-xl relative overflow-hidden shadow-lg">
          <button onClick={() => toggleSection('insights')} className="w-full px-6 py-5 flex items-center justify-between text-left relative z-10">
            <div>
              <h2 className="text-2xl font-bold">Clinical Insights</h2>
              <p className="text-teal-100/80 text-sm mt-1">High-level operational patterns for the week.</p>
            </div>
            <ChevronDown className={cn('text-teal-200 transition-transform', !openSections.insights && '-rotate-90')} size={20} />
          </button>
          {openSections.insights && (
            <div className="px-6 pb-6 relative z-10">
              <p className="text-teal-100/80 max-w-2xl text-lg leading-relaxed mb-6">
                Candidate intake has increased by <span className="text-white font-bold">18%</span> this quarter.
                Review initial-assessment capacity before opening more recurring slots.
              </p>
              <button className="bg-white/10 hover:bg-white/20 border border-white/20 text-white px-6 py-3 rounded-lg font-bold transition-colors">
                View Full Report
              </button>
            </div>
          )}
          <div className="absolute -right-10 -bottom-10 w-64 h-64 bg-white/5 rounded-full blur-3xl"></div>
          <div className="absolute right-8 top-8 w-16 h-16 bg-white/10 rounded-full border border-white/10 flex items-center justify-center">
            <ArrowRight size={32} className="text-teal-300" />
          </div>
        </section>
      </div>
    </div>
  );
};

const AccountSettings = () => {
  return (
    <div className="space-y-10 max-w-5xl">
      <section>
        <h1 className="text-3xl font-extrabold text-primary tracking-tight mb-2">Profile Settings</h1>
        <p className="text-secondary">Manage your professional credentials and account security.</p>
      </section>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2 space-y-8">
          <div className="bg-white rounded-xl shadow-sm p-8 border border-slate-100">
            <h3 className="text-lg font-bold mb-6 flex items-center gap-2">
              <Users size={20} className="text-primary" />
              Personal Information
            </h3>
            <div className="flex flex-col md:flex-row gap-10">
              <div className="flex flex-col items-center gap-4">
                <div className="relative group">
                  <img src="https://picsum.photos/seed/doctor/150/150" alt="Profile" className="w-32 h-32 rounded-xl object-cover ring-4 ring-slate-50 shadow-md" referrerPolicy="no-referrer" />
                  <button className="absolute -bottom-2 -right-2 bg-primary text-white p-2 rounded-lg shadow-lg hover:scale-105 transition-transform">
                    <Camera size={18} />
                  </button>
                </div>
                <p className="text-[10px] text-slate-400 font-medium text-center">JPG, GIF or PNG. Max size of 800K</p>
              </div>
              <div className="flex-1 space-y-6">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div className="space-y-2">
                    <label className="text-sm font-semibold text-slate-600">Full Name</label>
                    <input className="w-full rounded-lg border-slate-200 focus:border-primary focus:ring-primary/20 bg-slate-50 px-4 py-2.5" defaultValue="Dr. Julian Vance" />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-semibold text-slate-600">Professional Title</label>
                    <input className="w-full rounded-lg border-slate-200 focus:border-primary focus:ring-primary/20 bg-slate-50 px-4 py-2.5" defaultValue="Chief Resident" />
                  </div>
                  <div className="space-y-2 md:col-span-2">
                    <label className="text-sm font-semibold text-slate-600">Email Address</label>
                    <input className="w-full rounded-lg border-slate-200 focus:border-primary focus:ring-primary/20 bg-slate-50 px-4 py-2.5" defaultValue="j.vance@clinicalsanctuary.com" />
                  </div>
                </div>
                <div className="flex justify-end">
                  <button className="bg-primary text-white px-8 py-2.5 rounded-lg font-bold shadow-md hover:opacity-90 transition-all">Save Changes</button>
                </div>
              </div>
            </div>
          </div>

          <div className="bg-white rounded-xl shadow-sm p-8 border border-slate-100">
            <h3 className="text-lg font-bold mb-6 flex items-center gap-2">
              <ShieldCheck size={20} className="text-primary" />
              Security & Privacy
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="p-6 bg-slate-50 rounded-xl border border-slate-200">
                <h4 className="font-bold text-primary mb-2">Two-Factor Auth</h4>
                <p className="text-sm text-slate-500 mb-6">Add an extra layer of security to your account.</p>
                <button className="w-full border-2 border-primary text-primary font-bold py-2 rounded-lg hover:bg-primary/5 transition-all">Configure 2FA</button>
              </div>
              <div className="p-6 bg-slate-50 rounded-xl border border-slate-200">
                <h4 className="font-bold text-primary mb-2">Account Status</h4>
                <div className="space-y-2">
                  <div className="flex justify-between text-sm">
                    <span className="text-slate-500">Last Login</span>
                    <span className="font-bold">2 hours ago</span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-slate-500">Password Changed</span>
                    <span className="font-bold">62 days ago</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="space-y-6">
          <div className="bg-white rounded-xl shadow-sm p-6 border border-slate-100">
            <h3 className="font-bold mb-4">Notification Preferences</h3>
            <div className="space-y-4">
              {[
                { label: 'Email Alerts', icon: Mail, checked: true },
                { label: 'Message Notifications', icon: MessageSquare, checked: false },
                { label: 'Critical Lab Results', icon: AlertCircle, checked: true },
              ].map((item, i) => (
                <div key={i} className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <item.icon size={18} className="text-slate-400" />
                    <span className="text-sm font-medium">{item.label}</span>
                  </div>
                  <div className={cn(
                    "w-10 h-5 rounded-full relative cursor-pointer transition-colors",
                    item.checked ? "bg-primary" : "bg-slate-200"
                  )}>
                    <div className={cn(
                      "absolute top-1 w-3 h-3 bg-white rounded-full transition-all",
                      item.checked ? "right-1" : "left-1"
                    )}></div>
                  </div>
                </div>
              ))}
            </div>
          </div>
          <button className="w-full flex items-center justify-center gap-2 text-red-500 font-bold text-xs uppercase tracking-widest hover:bg-red-50 py-4 rounded-xl transition-colors">
            <Trash2 size={16} />
            Deactivate Account
          </button>
        </div>
      </div>
    </div>
  );
};

const GroupManager = () => {
  // Hebrew interface
  return (
    <div className="space-y-8 max-w-6xl" dir="rtl">
      <div className="flex justify-between items-end">
        <div>
          <nav className="flex gap-2 text-sm text-slate-400 mb-2">
            <span>קבוצות</span>
            <span>/</span>
            <span className="text-primary font-semibold">קבוצת גברים</span>
          </nav>
          <h1 className="text-4xl font-extrabold text-primary tracking-tight">קבוצת גברים</h1>
        </div>
        <button className="flex items-center gap-2 px-6 py-2 bg-primary text-white rounded-lg font-bold shadow-md hover:opacity-90 transition-all">
          <UserPlus size={18} />
          מפגש חדש
        </button>
      </div>

      <div className="flex gap-8 border-b border-slate-200 text-lg font-medium">
        <button className="pb-4 text-slate-400 hover:text-primary transition-colors">פרטי קבוצה</button>
        <button className="pb-4 border-b-2 border-primary text-primary font-bold">לוח זמנים</button>
        <button className="pb-4 text-slate-400 hover:text-primary transition-colors flex items-center gap-2">
          חברי קבוצה
          <span className="bg-slate-100 text-slate-500 text-xs px-2 py-0.5 rounded-full">5</span>
        </button>
        <button className="pb-4 text-slate-400 hover:text-primary transition-colors">היסטוריית חברים</button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-4 flex flex-col gap-6">
          <div className="bg-white rounded-xl p-6 shadow-sm border border-slate-100">
            <div className="flex justify-between items-start mb-6">
              <h3 className="text-xl font-bold text-primary">המפגש הקרוב</h3>
              <span className="bg-teal-50 text-teal-700 px-3 py-1 rounded-full text-xs font-bold">פעיל</span>
            </div>
            <div className="space-y-4 mb-8">
              <div className="flex items-center gap-4">
                <div className="bg-slate-50 p-3 rounded-lg text-primary"><CalendarIcon size={20} /></div>
                <div>
                  <p className="text-xs text-slate-400">תאריך</p>
                  <p className="font-bold">יום שלישי, 15 באוקטובר</p>
                </div>
              </div>
              <div className="flex items-center gap-4">
                <div className="bg-slate-50 p-3 rounded-lg text-primary"><Clock size={20} /></div>
                <div>
                  <p className="text-xs text-slate-400">שעה ומשך</p>
                  <p className="font-bold">18:00 (90 דקות)</p>
                </div>
              </div>
              <div className="flex items-center gap-4">
                <div className="bg-slate-50 p-3 rounded-lg text-primary"><MapPin size={20} /></div>
                <div>
                  <p className="text-xs text-slate-400">מיקום</p>
                  <p className="font-bold">חדר הדרכה 3 / זום</p>
                </div>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <button className="flex flex-col items-center gap-1 p-3 rounded-lg border border-slate-100 hover:bg-slate-50 transition-colors">
                <Edit2 size={16} className="text-slate-400" />
                <span className="text-xs font-semibold">עריכה</span>
              </button>
              <button className="flex flex-col items-center gap-1 p-3 rounded-lg border border-slate-100 hover:bg-slate-50 transition-colors">
                <Globe size={16} className="text-slate-400" />
                <span className="text-xs font-semibold">קישור</span>
              </button>
              <button className="flex flex-col items-center gap-1 p-3 rounded-lg border border-slate-100 hover:bg-red-50 text-red-500 transition-colors">
                <Trash2 size={16} />
                <span className="text-xs font-semibold">ביטול</span>
              </button>
            </div>
          </div>
        </div>

        <div className="lg:col-span-8 space-y-6">
          <div className="bg-white rounded-xl shadow-sm border border-slate-100 overflow-hidden">
            <div className="bg-slate-50 p-6 border-b border-slate-100 flex justify-between items-center">
              <div className="flex gap-4 items-center">
                <div className="bg-primary text-white w-12 h-12 rounded-lg flex flex-col items-center justify-center font-bold">
                  <span className="text-xs">08</span>
                  <span className="text-lg leading-none">אוק׳</span>
                </div>
                <div>
                  <h4 className="font-bold text-lg">מפגש 12: תקשורת בינאישית</h4>
                  <p className="text-sm text-slate-400">השתתפות: 4/5 חברים • מנחה: ד״ר איתן לוי</p>
                </div>
              </div>
              <button className="text-primary font-bold flex items-center gap-1 hover:underline">
                <FileText size={18} />
                פרוטוקול מלא
              </button>
            </div>
            <div className="p-6">
              <label className="block text-sm font-bold text-slate-500 mb-3">מה קרה במפגש הזה?</label>
              <div className="bg-slate-50 rounded-lg p-4 min-h-[120px] text-slate-700 leading-relaxed">
                המפגש התמקד בדפוסי תקשורת בתוך המשפחה. יוסי שיתף בקונפליקט משמעותי שהיה לו השבוע, והקבוצה נתנה פידבק תומך ומכבד. ניכר כי חברי הקבוצה מתחילים להרגיש בטוחים יותר לחשוף פגיעות. בוצע תרגיל של הקשבה פעילה.
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

const Calendar = () => {
  const days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'];
  const dates = ['05 Apr', '06 Apr', '07 Apr', '08 Apr', '09 Apr'];
  const hours = Array.from({ length: 12 }, (_, i) => `${i + 8}:00`);

  return (
    <div className="space-y-8 h-full flex flex-col">
      <div className="flex items-end justify-between">
        <div>
          <h3 className="text-3xl font-extrabold text-primary tracking-tight">Weekly Snapshot</h3>
          <div className="flex items-center gap-4 mt-1">
            <span className="text-slate-500 font-medium">05 Apr 2026 - 09 Apr 2026</span>
            <div className="flex gap-1">
              <button className="p-1 rounded hover:bg-slate-100 text-primary"><ChevronLeft size={20} /></button>
              <button className="p-1 rounded hover:bg-slate-100 text-primary"><ChevronRight size={20} /></button>
            </div>
          </div>
        </div>
        <div className="flex gap-4 items-center bg-white p-3 rounded-lg shadow-sm border border-slate-100">
          {['Ongoing', 'Candidate', 'Archived', 'Blocked', 'Group'].map((label, i) => (
            <div key={i} className="flex items-center gap-2 text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
              <span className={cn(
                "w-3 h-3 rounded-full",
                label === 'Ongoing' ? "bg-teal-800" :
                label === 'Candidate' ? "bg-indigo-500" :
                label === 'Archived' ? "bg-slate-400" :
                label === 'Blocked' ? "bg-red-500" : "bg-amber-500"
              )}></span>
              {label}
            </div>
          ))}
        </div>
      </div>

      <div className="flex-1 bg-white rounded-xl shadow-sm border border-slate-100 overflow-hidden flex flex-col">
        <div className="grid grid-cols-[80px_repeat(5,1fr)] border-b border-slate-100">
          <div className="p-4 bg-slate-50 border-r border-slate-100 flex items-center justify-center">
            <Clock size={18} className="text-slate-400" />
          </div>
          {days.map((day, i) => (
            <div key={i} className={cn("p-4 text-center", i > 0 && "border-l border-slate-100")}>
              <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">{day}</p>
              <p className="text-lg font-bold text-primary">{dates[i]}</p>
            </div>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto relative">
          <div className="grid grid-cols-[80px_repeat(5,1fr)] min-h-full">
            <div className="bg-slate-50 border-r border-slate-100">
              {hours.map((hour, i) => (
                <div key={i} className="h-16 flex items-start justify-center pt-2 text-[10px] font-bold text-slate-400">{hour}</div>
              ))}
            </div>
            {days.map((_, i) => (
              <div key={i} className="relative border-l border-slate-100">
                {i === 0 && (
                  <div className="absolute top-8 left-1 right-1 h-32 bg-teal-800 rounded-lg p-3 text-white shadow-md border-l-4 border-teal-300 cursor-pointer">
                    <h4 className="text-sm font-bold">Arthur Morgan</h4>
                    <p className="text-[11px] opacity-90">Post-Op Recovery</p>
                  </div>
                )}
                {i === 1 && (
                  <div className="absolute top-[128px] left-1 right-1 h-48 bg-amber-500 rounded-lg p-3 text-white shadow-md border-l-4 border-amber-200 cursor-pointer">
                    <h4 className="text-sm font-bold">Pain Management B</h4>
                    <p className="text-[11px] opacity-90">8 Participants</p>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

const AddPatient = () => {
  return (
    <div className="space-y-8 max-w-6xl">
      <div>
        <nav className="flex items-center gap-2 text-xs text-slate-400 mb-2">
          <span>Patients</span>
          <ChevronRight size={14} />
          <span className="text-primary font-semibold">Add New Patient</span>
        </nav>
        <h2 className="text-3xl font-extrabold text-primary tracking-tight">Add New Patient</h2>
        <p className="text-slate-500 mt-1">Register a new patient into the clinic system with HIPAA-compliant security.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        <div className="lg:col-span-4 space-y-8">
          <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm text-center">
            <h3 className="text-sm font-bold text-slate-700 mb-4 text-left uppercase tracking-wider">Patient Profile Photo</h3>
            <div className="w-32 h-32 mx-auto rounded-full bg-slate-100 border-2 border-dashed border-slate-300 flex flex-col items-center justify-center overflow-hidden hover:border-primary transition-colors cursor-pointer">
              <Camera size={32} className="text-slate-400" />
              <span className="text-[10px] text-slate-500 mt-1 font-medium">Upload Image</span>
            </div>
            <p className="text-[11px] text-slate-400 mt-4 leading-relaxed italic">JPG or PNG, max 5MB.</p>
          </div>

          <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm space-y-4">
            <h3 className="text-sm font-bold text-slate-700 uppercase tracking-wider">Contact Channels</h3>
            <div className="space-y-1">
              <label className="text-xs font-bold text-slate-500">Email Address</label>
              <div className="relative">
                <Mail size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                <input className="w-full pl-9 pr-4 py-2.5 rounded-lg border-slate-200 focus:border-primary focus:ring-1 focus:ring-primary text-sm" placeholder="patient@example.com" />
              </div>
            </div>
            <div className="space-y-1">
              <label className="text-xs font-bold text-slate-500">Primary Phone</label>
              <div className="relative">
                <Phone size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                <input className="w-full pl-9 pr-4 py-2.5 rounded-lg border-slate-200 focus:border-primary focus:ring-1 focus:ring-primary text-sm" placeholder="+1 (555) 000-0000" />
              </div>
            </div>
          </div>
        </div>

        <div className="lg:col-span-8 space-y-8">
          <div className="bg-white p-8 rounded-xl border border-slate-200 shadow-sm">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="md:col-span-2 space-y-1">
                <label className="text-xs font-bold text-slate-500">Full Legal Name</label>
                <input className="w-full px-4 py-2.5 rounded-lg border-slate-200 focus:border-primary focus:ring-1 focus:ring-primary text-sm" placeholder="As it appears on government-issued ID" />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-bold text-slate-500">Date of Birth</label>
                <input className="w-full px-4 py-2.5 rounded-lg border-slate-200 focus:border-primary focus:ring-1 focus:ring-primary text-sm" type="date" />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-bold text-slate-500">Gender Identity</label>
                <select className="w-full px-4 py-2.5 rounded-lg border-slate-200 focus:border-primary focus:ring-1 focus:ring-primary text-sm">
                  <option value="">Select gender</option>
                  <option>Male</option>
                  <option>Female</option>
                  <option>Non-binary</option>
                </select>
              </div>
            </div>
          </div>

          <div className="bg-white p-8 rounded-xl border border-slate-200 shadow-sm">
            <h3 className="text-sm font-bold text-slate-700 mb-6 uppercase tracking-wider">Residential Address</h3>
            <div className="grid grid-cols-1 md:grid-cols-6 gap-4">
              <div className="md:col-span-6 space-y-1">
                <label className="text-xs font-bold text-slate-500">Street Address</label>
                <input className="w-full px-4 py-2.5 rounded-lg border-slate-200 focus:border-primary focus:ring-1 focus:ring-primary text-sm" placeholder="e.g., 123 Health Ave" />
              </div>
              <div className="md:col-span-3 space-y-1">
                <label className="text-xs font-bold text-slate-500">City</label>
                <input className="w-full px-4 py-2.5 rounded-lg border-slate-200 focus:border-primary focus:ring-1 focus:ring-primary text-sm" />
              </div>
              <div className="md:col-span-1 space-y-1">
                <label className="text-xs font-bold text-slate-500">State</label>
                <input className="w-full px-4 py-2.5 rounded-lg border-slate-200 focus:border-primary focus:ring-1 focus:ring-primary text-sm text-center" placeholder="CA" />
              </div>
              <div className="md:col-span-2 space-y-1">
                <label className="text-xs font-bold text-slate-500">Zip Code</label>
                <input className="w-full px-4 py-2.5 rounded-lg border-slate-200 focus:border-primary focus:ring-1 focus:ring-primary text-sm" />
              </div>
            </div>
          </div>

          <div className="flex items-center justify-between pt-4">
            <button className="px-6 py-3 rounded-lg text-slate-500 font-bold hover:bg-slate-100 transition-colors">Save as Draft</button>
            <button className="px-8 py-3 bg-primary text-white rounded-lg font-bold shadow-lg hover:opacity-90 transition-all flex items-center gap-2 group">
              Next Step: Medical History
              <ArrowRight size={18} className="group-hover:translate-x-1 transition-transform" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

const PatientList = () => {
  const patients = [
    { name: 'Sarah Jenkins', type: 'Private', status: 'Ongoing', email: 'sarah.j@email.com', phone: '+1 (555) 012-3456', lastVisit: 'Oct 12, 2023', image: 'https://picsum.photos/seed/sarah/100/100' },
    { name: 'Arthur Miller', type: 'Residency', status: 'Candidate', email: 'arthur.m@email.com', phone: '+1 (555) 098-7654', lastVisit: 'Sep 28, 2023', image: 'https://picsum.photos/seed/arthur/100/100' },
    { name: 'Elena Rodriguez', type: 'Group', status: 'Ongoing', email: 'elena.rod@email.com', phone: '+1 (555) 876-5432', lastVisit: 'Oct 14, 2023', image: 'https://picsum.photos/seed/elena/100/100' },
    { name: 'Kevin Thorne', type: 'Initial Intake', status: 'Candidate', email: 'k.thorne@domain.com', phone: '+1 (555) 345-6789', lastVisit: 'Oct 10, 2023', image: 'https://picsum.photos/seed/kevin/100/100' },
    { name: 'Nora Patel', type: 'Diagnosee', status: 'Archived', email: 'n.patel@domain.com', phone: '+1 (555) 765-1098', lastVisit: 'Aug 26, 2023', image: 'https://picsum.photos/seed/nora/100/100' },
  ];

  return (
    <div className="space-y-8">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-extrabold text-primary tracking-tight">Patients</h1>
          <p className="text-slate-500 mt-1">Manage and monitor clinic member records.</p>
        </div>
        <button className="flex items-center justify-center gap-2 px-5 py-2.5 bg-primary text-white font-semibold rounded-xl shadow-md hover:opacity-90 transition-all">
          <UserPlus size={18} />
          New Patient
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 xl:grid-cols-4 gap-4">
        {[
          { label: 'Candidate', value: '2', change: 'Awaiting next step', icon: Users, color: 'text-blue-600', bg: 'bg-blue-50' },
          { label: 'Appointments', value: '42', change: 'Scheduled today', icon: CalendarIcon, color: 'text-amber-600', bg: 'bg-amber-50' },
          { label: 'Treatment Types', value: '5', change: 'One sample per type', icon: UserPlus, color: 'text-purple-600', bg: 'bg-purple-50' },
          { label: 'Avg. Wait Time', value: '18 min', change: '-5m from avg', icon: Clock, color: 'text-red-600', bg: 'bg-red-50' },
        ].map((stat, i) => (
          <div key={i} className="bg-white p-5 rounded-2xl shadow-sm border border-slate-100 flex flex-col justify-between">
            <div className="flex justify-between items-start">
              <span className="text-slate-500 text-sm font-medium">{stat.label}</span>
              <div className={cn("p-2 rounded-lg", stat.bg, stat.color)}>
                <stat.icon size={18} />
              </div>
            </div>
            <div className="mt-4">
              <span className="text-2xl font-bold">{stat.value}</span>
              <span className={cn("text-xs ml-2 font-semibold", i === 1 ? "text-slate-400 font-medium" : stat.color)}>{stat.change}</span>
            </div>
          </div>
        ))}
      </div>

      <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
        <div className="p-4 border-b border-slate-100 flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <button className="px-4 py-2 bg-slate-50 hover:bg-slate-100 text-slate-700 text-sm font-semibold rounded-lg flex items-center gap-2 transition-colors">
              <Filter size={16} />
              Filter
            </button>
            <button className="px-4 py-2 bg-white border border-slate-200 hover:border-slate-300 text-slate-700 text-sm font-semibold rounded-lg flex items-center gap-2 transition-colors">
              <ArrowUpDown size={16} />
              Sort: A-Z
            </button>
          </div>
          <div className="flex items-center gap-2 text-slate-500 text-xs font-medium">
            <span>Showing 5 curated patient types</span>
            <div className="flex gap-1 ml-4">
              <button className="p-1 hover:bg-slate-50 rounded disabled:opacity-30"><ChevronLeft size={18} /></button>
              <button className="p-1 hover:bg-slate-50 rounded"><ChevronRight size={18} /></button>
            </div>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-left table-fixed">
            <thead>
              <tr className="bg-slate-50/50 text-slate-500 text-xs font-bold uppercase tracking-wider">
                <th className="px-6 py-4">Patient Name</th>
                <th className="px-6 py-4">Type</th>
                <th className="px-6 py-4">Status</th>
                <th className="px-6 py-4">Contact</th>
                <th className="px-6 py-4">Last Visit</th>
                <th className="px-6 py-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {patients.map((patient, i) => (
                <tr key={i} className="hover:bg-slate-50/80 transition-colors group">
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <img src={patient.image} alt={patient.name} className="w-10 h-10 rounded-full object-cover border-2 border-white shadow-sm" referrerPolicy="no-referrer" />
                      <div>
                        <div className="font-bold text-slate-900 text-sm">{patient.name}</div>
                        <div className="text-xs text-slate-400">Focused example patient</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4 text-sm text-slate-600">{patient.type}</td>
                  <td className="px-6 py-4">
                    <span className={cn(
                      "inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium",
                      patient.status === 'Ongoing' ? "bg-green-100 text-green-800" :
                      patient.status === 'Candidate' ? "bg-amber-100 text-amber-800" :
                      "bg-slate-100 text-slate-800"
                    )}>
                      {patient.status}
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    <div className="text-sm text-slate-900">{patient.email}</div>
                    <div className="text-xs text-slate-400">{patient.phone}</div>
                  </td>
                  <td className="px-6 py-4 text-sm text-slate-600">{patient.lastVisit}</td>
                  <td className="px-6 py-4 text-right">
                    <div className="flex items-center justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button className="p-2 text-slate-400 hover:text-primary transition-colors"><Eye size={18} /></button>
                      <button className="p-2 text-slate-400 hover:text-primary transition-colors"><Edit2 size={18} /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

const Help = () => {
  return (
    <div className="space-y-12 max-w-6xl">
      <section className="relative overflow-hidden rounded-2xl bg-primary text-white p-12 shadow-xl">
        <div className="relative z-10 max-w-2xl">
          <h1 className="text-4xl md:text-5xl font-extrabold mb-4 tracking-tight">How can we help you today?</h1>
          <p className="text-teal-100 text-lg mb-8">Get direct support from your clinical team or find answers on how to manage your care journey.</p>
          <div className="flex items-center gap-4 p-4 bg-white/10 backdrop-blur-md rounded-xl border border-white/20">
            <img src="https://picsum.photos/seed/doctor2/100/100" alt="Therapist" className="w-16 h-16 rounded-lg object-cover" referrerPolicy="no-referrer" />
            <div>
              <p className="text-sm font-medium opacity-80 uppercase tracking-wider">Your Primary Therapist</p>
              <h3 className="text-xl font-bold">Dr. Sarah Henderson</h3>
              <div className="flex items-center gap-2 text-sm mt-1">
                <span className="w-2 h-2 bg-green-400 rounded-full animate-pulse"></span>
                <span>Online Now</span>
              </div>
            </div>
          </div>
        </div>
        <div className="absolute right-0 top-0 w-1/3 h-full opacity-10">
          <ShieldCheck size={300} className="translate-x-1/4 -translate-y-1/4" />
        </div>
      </section>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {[
          { title: 'Message your Therapist', desc: 'Send a secure message directly to Dr. Henderson. Typical response: 2-4 hours.', icon: MessageSquare, action: 'Start Conversation', color: 'bg-blue-50 text-blue-600' },
          { title: 'Email Support', desc: 'For billing, technical issues, or records requests. Our admin team is here to help.', icon: Mail, action: 'support@ethosmed.com', color: 'bg-slate-50 text-slate-600' },
          { title: 'Call Clinic', desc: 'Available Mon-Fri, 8am-6pm for urgent matters or appointment changes.', icon: Phone, action: '+1 (555) 012-3456', color: 'bg-amber-50 text-amber-600' },
        ].map((item, i) => (
          <div key={i} className="bg-white p-8 rounded-2xl border border-slate-100 hover:shadow-lg transition-shadow group cursor-pointer">
            <div className={cn("w-14 h-14 rounded-xl flex items-center justify-center mb-6 group-hover:scale-110 transition-transform", item.color)}>
              <item.icon size={28} />
            </div>
            <h3 className="text-xl font-bold mb-2">{item.title}</h3>
            <p className="text-slate-500 text-sm mb-6 leading-relaxed">{item.desc}</p>
            <button className={cn(
              "w-full py-3 font-semibold rounded-lg transition-colors",
              i === 0 ? "bg-primary text-white" : "border-2 border-slate-200 text-slate-600 hover:bg-slate-50"
            )}>
              {item.action}
            </button>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-8">
        <div className="lg:col-span-3 bg-white rounded-2xl border border-slate-100 overflow-hidden shadow-sm">
          <div className="p-6 border-b border-slate-100 flex items-center justify-between">
            <div>
              <h2 className="text-2xl font-bold">Office Location</h2>
              <p className="text-slate-500">Visit us for in-person consultations</p>
            </div>
            <MapPin size={32} className="text-primary" />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2">
            <div className="p-8 space-y-6">
              <div>
                <h4 className="font-bold text-xs uppercase text-slate-400 mb-2">Address</h4>
                <p className="text-slate-900 font-medium">1200 Medical Plaza, Suite 400<br/>Central Business District<br/>New York, NY 10001</p>
              </div>
              <div>
                <h4 className="font-bold text-xs uppercase text-slate-400 mb-2">Office Hours</h4>
                <ul className="space-y-1 text-sm">
                  <li className="flex justify-between"><span>Mon - Thu</span> <span className="font-semibold">8:00 AM - 7:00 PM</span></li>
                  <li className="flex justify-between"><span>Friday</span> <span className="font-semibold">8:00 AM - 5:00 PM</span></li>
                  <li className="flex justify-between"><span>Sat - Sun</span> <span className="font-semibold text-red-500">Closed</span></li>
                </ul>
              </div>
              <button className="flex items-center gap-2 text-primary font-bold hover:underline">
                <ArrowRight size={18} />
                Get Directions
              </button>
            </div>
            <div className="h-64 md:h-auto bg-slate-100 relative overflow-hidden">
              <img src="https://picsum.photos/seed/map/400/400" alt="Map" className="w-full h-full object-cover grayscale opacity-50" referrerPolicy="no-referrer" />
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="w-10 h-10 bg-primary text-white rounded-full flex items-center justify-center shadow-2xl ring-8 ring-primary/20">
                  <Stethoscope size={20} />
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="lg:col-span-2 bg-slate-50 rounded-2xl p-8 border border-slate-100">
          <h2 className="text-2xl font-bold mb-6">Portal Guide</h2>
          <div className="space-y-8">
            {[
              { title: 'Book an Appointment', desc: "Navigate to the 'Schedule' tab to pick a time slot. You'll receive a confirmation instantly." },
              { title: 'View Medical Records', desc: "Access your 'Profile' section to download session notes and lab results securely." },
              { title: 'Billing & Payments', desc: "Check your current balance and pay invoices directly from the 'Settings' menu." },
            ].map((step, i) => (
              <div key={i} className="flex gap-4">
                <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary text-white flex items-center justify-center font-bold text-sm">{i + 1}</div>
                <div>
                  <h4 className="font-bold mb-1">{step.title}</h4>
                  <p className="text-sm text-slate-500 leading-relaxed">{step.desc}</p>
                </div>
              </div>
            ))}
          </div>
          <div className="mt-12 p-6 bg-primary/5 rounded-xl border border-primary/10">
            <h4 className="font-bold flex items-center gap-2 mb-2 text-primary">
              <Info size={18} />
              Pro Tip
            </h4>
            <p className="text-xs text-slate-500 leading-relaxed">Turn on push notifications to get reminders 30 minutes before your sessions.</p>
          </div>
        </div>
      </div>
    </div>
  );
};

// --- Main App ---

export default function App() {
  const [screen, setScreen] = useState<Screen>('dashboard');

  const getTitle = () => {
    switch(screen) {
      case 'dashboard': return 'Dashboard';
      case 'settings': return 'Account Settings';
      case 'groups': return 'Group Manager';
      case 'calendar': return 'Weekly Calendar';
      case 'add-patient': return 'Add New Patient';
      case 'patients': return 'Patient List';
      case 'help': return 'Support & Help';
      default: return 'Sanctuary CRM';
    }
  };

  return (
    <div className="min-h-screen flex">
      <Sidebar activeScreen={screen} setScreen={setScreen} />
      
      <div className="flex-1 ml-64 flex flex-col">
        <TopNav title={getTitle()} />
        
        <main className="mt-16 p-8 flex-1 overflow-y-auto">
          <AnimatePresence mode="wait">
            <motion.div
              key={screen}
              initial={{ opacity: 0, x: 10 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -10 }}
              transition={{ duration: 0.2 }}
              className="h-full"
            >
              {screen === 'dashboard' && <Dashboard />}
              {screen === 'settings' && <AccountSettings />}
              {screen === 'groups' && <GroupManager />}
              {screen === 'calendar' && <Calendar />}
              {screen === 'add-patient' && <AddPatient />}
              {screen === 'patients' && <PatientList />}
              {screen === 'help' && <Help />}
            </motion.div>
          </AnimatePresence>
        </main>

        <footer className="p-8 border-t border-slate-100 text-center text-slate-400 text-sm">
          Ethos Medical CRM Portal © 2024. All communications are HIPAA compliant and encrypted.
        </footer>
      </div>

      {/* Floating Action Button for Emergency */}
      <button className="fixed bottom-8 right-8 w-14 h-14 bg-red-500 text-white rounded-full shadow-2xl flex items-center justify-center hover:scale-110 transition-transform z-50 group">
        <AlertCircle size={28} />
        <span className="absolute right-16 bg-slate-900 text-white text-[10px] px-2 py-1 rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap uppercase tracking-widest font-bold">
          Emergency Protocol
        </span>
      </button>
    </div>
  );
}
