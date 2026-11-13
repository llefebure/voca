'use client'

import { useState, useEffect } from 'react'
import { supabase } from '@/lib/supabase'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useRouter } from 'next/navigation'
import { Target, Settings, BookOpen, Save, X, TrendingUp } from 'lucide-react'
import { DashboardLayout } from '@/components/dashboard-layout'
import { useLanguage } from '@/components/language-context'
import { toast } from '@/components/ui/toast'
import { languageName } from '@/lib/languages'

type ProfileFields = {
  target_language?: string
  level?: string
  goals?: string
  interests?: string
}

export default function ProfilePage() {
  const [profile, setProfile] = useState<ProfileFields | null>(null)
  const [isEditing, setIsEditing] = useState(false)
  const [edited, setEdited] = useState<{ level?: string; goals?: string; interests?: string }>({})
  const [loading, setLoading] = useState(true)
  const router = useRouter()
  // The profile page shows and edits the *active language's* learner details
  // (level/goals/interests live per language in user_languages). Switching languages
  // happens in the sidebar dropdown.
  const { activeLanguage, practicedLanguages, refresh: refreshLanguages } = useLanguage()

  useEffect(() => {
    const fetchProfile = async () => {
      try {
        const { data: { user } } = await supabase.auth.getUser()
        if (!user) {
          router.push('/auth')
          return
        }

        const { data } = await supabase
          .from('profiles')
          .select('*')
          .eq('id', user.id)
          .single()

        setProfile(data)
      } catch (error) {
        console.error('Error fetching profile:', error)
      } finally {
        setLoading(false)
      }
    }
    fetchProfile()
  }, [router])

  // Learner details for the active language: its user_languages row if onboarded,
  // otherwise the legacy profile fields (pre-multi-language data).
  const activeRow = practicedLanguages.find((row) => row.language === activeLanguage)
  const level = activeRow?.level ?? profile?.level ?? null
  const goals = activeRow?.goals ?? profile?.goals ?? null
  const interests = activeRow?.interests ?? profile?.interests ?? null

  const startEditing = () => {
    setEdited({ level: level ?? undefined, goals: goals ?? undefined, interests: interests ?? undefined })
    setIsEditing(true)
  }

  const handleSave = async () => {
    try {
      const { data: { user } } = await supabase.auth.getUser()
      if (!user || !activeLanguage) throw new Error('Signed out')
      // Per-language details upsert the user_languages row for the active language;
      // last_practiced_at is intentionally not included (never reset by edit).
      const { error } = await supabase.from('user_languages').upsert({
        user_id: user.id,
        language: activeLanguage,
        level: edited.level ?? null,
        goals: edited.goals ?? null,
        interests: edited.interests ?? null,
      })
      if (error) throw error
      await refreshLanguages()
      setIsEditing(false)
      toast({
        title: "Profile Updated",
        description: `Your ${languageName(activeLanguage)} learning profile has been saved.`,
        type: "success",
      })
    } catch {
      toast({
        title: "Save Failed",
        description: "Could not save your profile changes.",
        type: "error",
      })
    }
  }

  if (loading) return (
    <DashboardLayout title="Profile">
      <div className="flex h-full items-center justify-center text-muted-foreground">Loading profile...</div>
    </DashboardLayout>
  )

  return (
    <DashboardLayout title="My Profile">
      <div className="mx-auto max-w-4xl space-y-8 p-4 md:p-8">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {/* Title is in DashboardLayout */}
          </div>
          <Button variant="outline" onClick={() => router.push('/')}>
            Return to Chat
          </Button>
        </div>

        <div className="grid gap-6 md:grid-cols-3">
          <Card className="md:col-span-1 border-t-4 border-t-primary">
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Settings className="h-5 w-5 text-muted-foreground" />
                Account
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="space-y-2">
                <Label className="text-xs text-muted-foreground uppercase tracking-wider">Target language</Label>
                <p className="text-2xl font-bold">{languageName(activeLanguage)}</p>
                <p className="text-xs text-muted-foreground">Switch languages from the sidebar.</p>
              </div>
              <div className="space-y-2">
                <Label className="text-xs text-muted-foreground uppercase tracking-wider">Current Level</Label>
                <p className="text-2xl font-bold">{level || 'Not set'}</p>
              </div>
              <Button 
                className="w-full rounded-lg" 
                variant={isEditing ? 'outline' : 'default'} 
                onClick={() => (isEditing ? setIsEditing(false) : startEditing())}
              >
                {isEditing ? (
                  <span className="flex items-center gap-2"><X className="h-4 w-4" /> Cancel</span>
                ) : (
                  'Edit Profile'
                )}
              </Button>
            </CardContent>
          </Card>

          <Card className="md:col-span-2">
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Target className="h-5 w-5 text-muted-foreground" />
                {languageName(activeLanguage)} Goals &amp; Interests
              </CardTitle>
            </CardHeader>
            <CardContent>
              {isEditing ? (
                <div className="space-y-4">
                  <div className="space-y-2">
                    <Label>Level</Label>
                    <div className="grid grid-cols-2 gap-2">
                      {['A2', 'B1', 'B2', 'C1'].map((lvl) => (
                        <Button
                          key={lvl}
                          variant={edited.level === lvl ? 'default' : 'outline'}
                          onClick={() => setEdited({ ...edited, level: lvl })}
                        >
                          {lvl}
                        </Button>
                      ))}
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label>Goals</Label>
                    <Input 
                      value={edited.goals ?? ''} 
                      onChange={(e) => setEdited({ ...edited, goals: e.target.value })} 
                      className="rounded-lg"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>Interests</Label>
                    <Input 
                      value={edited.interests ?? ''} 
                      onChange={(e) => setEdited({ ...edited, interests: e.target.value })} 
                      className="rounded-lg"
                    />
                  </div>
                  <Button className="w-full rounded-lg flex items-center gap-2" onClick={handleSave}>
                    <Save className="h-4 w-4" /> Save Changes
                  </Button>
                </div>
              ) : (
                <div className="grid gap-6">
                  <div className="space-y-2">
                    <p className="text-sm font-medium text-muted-foreground uppercase tracking-wider">My Goals</p>
                    <p className="text-foreground leading-relaxed">{goals || 'No goals set yet.'}</p>
                  </div>
                  <div className="space-y-2">
                    <p className="text-sm font-medium text-muted-foreground uppercase tracking-wider">Interests</p>
                    <p className="text-foreground leading-relaxed">{interests || 'No interests set yet.'}</p>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <Card className="border-t-4 border-t-primary/30">
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <BookOpen className="h-5 w-5 text-muted-foreground" />
              SRS Progress
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col items-center justify-center py-12 text-center space-y-3">
              <div className="bg-muted p-4 rounded-full">
                <TrendingUp className="h-8 w-8 text-muted-foreground" />
              </div>
              <p className="text-muted-foreground italic">
                Your spaced repetition progress will be visualized here.
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    </DashboardLayout>
  )
}
