"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import {
  MessageSquare,
  History,
  BookOpen,
  User,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Languages,
  LogOut,
  PlusIcon,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuCheckboxItem, DropdownMenuItem, DropdownMenuGroup, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuShortcut } from "@/components/ui/dropdown-menu"
import { useLanguage } from "@/components/language-context"
import { SUPPORTED_LANGUAGES, UPCOMING_LANGUAGES, languageName } from "@/lib/languages"
import { supabase } from "@/lib/supabase"
import { useRouter } from "next/navigation"

const navItems = [
  { name: "Chat", href: "/", icon: MessageSquare },
  { name: "History", href: "/history", icon: History },
  { name: "Library", href: "/library", icon: BookOpen },
  { name: "Profile", href: "/profile", icon: User },
]

export function Sidebar() {
  const [isCollapsed, setIsCollapsed] = React.useState(false)
  const pathname = usePathname()
  const router = useRouter()
  const { activeLanguage, practicedLanguages, toggleLanguage, addLanguage } = useLanguage()

  // Supported languages the user has not onboarded yet; they can be switched to
  // directly (onboarding details arrive later via Profile / re-onboarding).
  const practiced = new Set(practicedLanguages.map((row) => row.language))
  const supportedNotPracticed = SUPPORTED_LANGUAGES.filter((lang) => !practiced.has(lang.code))

  const handleSignOut = async () => {
    await supabase.auth.signOut()
    router.push('/auth')
  }

  return (
    <aside 
      className={cn(
        "relative h-screen bg-background border-r transition-all duration-300 flex flex-col",
        isCollapsed ? "w-16" : "w-64"
      )}
    >
      {/* Language switcher: the header itself. Collapsed, the logo is the trigger. */}
      <DropdownMenu>
        <div className="p-4 flex items-center gap-3 overflow-hidden">
          {isCollapsed ? (
            <DropdownMenuTrigger
              render={
                <button className="bg-primary p-2 rounded-lg shrink-0 text-primary-foreground cursor-pointer hover:bg-primary/90 transition-colors">
                  <Languages className="size-5" />
                </button>
              }
            />
          ) : (
            <div className="bg-primary p-2 rounded-lg shrink-0">
              <Languages className="size-5 text-primary-foreground" />
            </div>
          )}
          {!isCollapsed && (
            <DropdownMenuTrigger
              render={
                <button className="flex w-full min-w-0 items-center justify-between gap-2 rounded-md px-2 py-1 text-left cursor-pointer hover:bg-accent transition-colors">
                  <span className="flex flex-col min-w-0 leading-tight">
                    <span className="text-xs text-muted-foreground truncate">Voca Tutor</span>
                    <span className="font-semibold truncate">
                      {activeLanguage ? languageName(activeLanguage) : "Loading…"}
                    </span>
                  </span>
                  <ChevronDown className="size-4 shrink-0 text-muted-foreground" />
                </button>
              }
            />
          )}
        </div>
        <DropdownMenuContent align="start" className="w-56">
          {/* GroupLabel requires a Group ancestor (Base UI contract). */}
          <DropdownMenuGroup>
            <DropdownMenuLabel>Learning language</DropdownMenuLabel>
            {practicedLanguages.map((row) => (
              <DropdownMenuCheckboxItem
                key={row.language}
                checked={row.language === activeLanguage}
                onSelect={() => void toggleLanguage(row.language)}
              >
                {languageName(row.language)}
              </DropdownMenuCheckboxItem>
            ))}
            {supportedNotPracticed.map((lang) => (
              <DropdownMenuItem key={lang.code} onSelect={() => void toggleLanguage(lang.code)}>
                {lang.name}
              </DropdownMenuItem>
            ))}
            {UPCOMING_LANGUAGES.map((name) => (
              <DropdownMenuItem key={name} disabled>
                {name}
                <span className="ml-auto text-xs text-muted-foreground">Soon</span>
              </DropdownMenuItem>
            ))}
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={addLanguage}>
            <PlusIcon className="size-4" />
            Add language…
            <DropdownMenuShortcut>Full setup</DropdownMenuShortcut>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <nav className="flex-1 px-2 space-y-1 py-4">
        {navItems.map((item) => {
          const isActive = pathname === item.href
          const Icon = item.icon
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 px-3 py-2 rounded-md transition-colors",
                isActive 
                  ? "bg-accent text-accent-foreground" 
                  : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
              )}
            >
              <Icon className="h-5 w-5 shrink-0" />
              {!isCollapsed && <span className="truncate">{item.name}</span>}
            </Link>
          )
        })}
      </nav>

      <div className="p-2 border-t space-y-1">
        <Button 
          variant="ghost" 
          className={cn(
            "w-full justify-start gap-3 text-muted-foreground hover:text-destructive",
            isCollapsed && "justify-center px-0"
          )}
          onClick={handleSignOut}
        >
          <LogOut className="h-5 w-5 shrink-0" />
          {!isCollapsed && <span className="truncate">Sign Out</span>}
        </Button>
        
        <Button 
          variant="ghost" 
          size="icon" 
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="w-full justify-center"
        >
          {isCollapsed ? <ChevronRight className="h-5 w-5" /> : <ChevronLeft className="h-5 w-5" />}
        </Button>
      </div>
    </aside>
  )
}
