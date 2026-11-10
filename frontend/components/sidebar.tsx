"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { 
  MessageSquare, 
  History, 
  BookOpen, 
  User, 
  ChevronLeft, 
  ChevronRight,
  Languages,
  LogOut
} from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
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
      <div className="p-4 flex items-center gap-3 overflow-hidden">
        <div className="bg-primary p-2 rounded-lg shrink-0">
          <Languages className="h-5 w-5 text-primary-foreground" />
        </div>
        {!isCollapsed && (
          <span className="font-bold text-xl truncate">Voca Tutor</span>
        )}
      </div>

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
