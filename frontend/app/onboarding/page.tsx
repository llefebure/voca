'use client'

import { useState } from 'react'
import { supabase } from '@/lib/supabase'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent } from '@/components/ui/card'
import { useRouter } from 'next/navigation'
import { CheckCircle, Target, Mic, ChevronRight } from 'lucide-react'
import { toast } from '@/components/ui/toast'
import {
  DEFAULT_LANGUAGE,
  SUPPORTED_LANGUAGES,
  UPCOMING_LANGUAGES,
} from '@/lib/languages'

type OnboardingStep = 'setup' | 'goals' | 'complete'

export default function OnboardingPage() {
  const [step, setStep] = useState<OnboardingStep>('setup')
  const [formData, setFormData] = useState({
    target_language: DEFAULT_LANGUAGE as string,
    level: 'B1',
    goals: '',
    interests: ''
  })
  const router = useRouter()

  const steps: { id: OnboardingStep; label: string }[] = [
    { id: 'setup', label: 'Level' },
    { id: 'goals', label: 'Goals' },
  ]
  const stepIndex = steps.findIndex((s) => s.id === step)

  const nextStep = () => {
    if (step === 'setup') setStep('goals')
  }

  const completeOnboarding = async () => {
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return

    try {
      // The profiles row already exists — the on_auth_user_created trigger
      // creates it at signup — so this update stamps the target-language pointer
      // and the onboarding completion time. supabase-js never throws on failed
      // writes; errors come back in-band, so each result must be checked here or
      // failures silently "succeed".
      const { data: updated, error: profilesError } = await supabase
        .from('profiles')
        .update({
          target_language: formData.target_language,
          onboarded_at: new Date().toISOString()
        })
        .eq('id', user.id)
        .select('id')
      if (profilesError) throw profilesError
      // 0 rows ⇒ the profile row is missing (RLS or trigger failure): surface
      // the setup error instead of "succeeding" into a chat page that would
      // bounce straight back to onboarding.
      if (!updated || updated.length === 0) throw new Error('Profile row missing')
      // Per-language learner details live in user_languages — the single write
      // of this context (profiles' legacy level/goals/interests copies are gone
      // from the schema). last_practiced_at is untouched so re-onboarding never
      // resets the practiced ordering.
      const { error: userLanguagesError } = await supabase.from('user_languages').upsert({
        user_id: user.id,
        language: formData.target_language,
        level: formData.level,
        goals: formData.goals,
        interests: formData.interests
      })
      if (userLanguagesError) throw userLanguagesError
      setStep('complete')
    } catch {
      toast({
        title: "Setup Error",
        description: "Failed to complete onboarding.",
        type: "error",
      })
    }
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <Card className="w-full max-w-2xl shadow-xl overflow-hidden border-none bg-card">
        <div className="bg-primary p-8 text-primary-foreground">
          <div className="flex justify-between items-center">
            <div>
              <h1 className="text-3xl font-bold">Welcome to Voca</h1>
              <p className="text-primary-foreground/80 mt-1">Let&apos;s personalize your learning journey</p>
            </div>
            <div className="hidden md:flex gap-2">
              {steps.map((s, i) => (
                <div 
                  key={s.id} 
                  className={`h-1.5 w-8 rounded-full transition-colors ${
                    stepIndex < 0 || i <= stepIndex 
                    ? 'bg-white' 
                    : 'bg-primary-foreground/30'
                  }`}
                />
              ))}
            </div>
          </div>
        </div>

        <CardContent className="p-8">
          {step === 'setup' && (
            <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
              <div className="text-center space-y-3">
                <div className="mx-auto w-16 h-16 bg-primary/10 text-primary rounded-full flex items-center justify-center mb-4">
                  <Mic className="h-8 w-8" />
                </div>
                <h2 className="text-2xl font-bold">Your current level</h2>
                <p className="text-muted-foreground">We&apos;ll adjust the tutor&apos;s vocabulary and grammar to match your skills.</p>
              </div>
              <div className="space-y-6">
                <div className="space-y-3">
                  <Label className="text-sm font-medium">Self-assessed Level</Label>
                  <div className="grid grid-cols-2 gap-3">
                    {['A2', 'B1', 'B2', 'C1'].map((lvl) => (
                      <Button 
                        key={lvl}
                        variant={formData.level === lvl ? 'default' : 'outline'}
                        className="h-12 text-lg"
                        onClick={() => setFormData({...formData, level: lvl})}
                      >
                        {lvl} {lvl === 'A2' ? '(Elementary)' : lvl === 'B1' ? '(Intermediate)' : lvl === 'B2' ? '(Upper Inter)' : '(Advanced)'}
                      </Button>
                    ))}
                  </div>
                </div>
              </div>
              <Button className="w-full h-12 rounded-xl text-lg" onClick={nextStep}>
                Continue <ChevronRight className="ml-2 h-5 w-5" />
              </Button>
            </div>
          )}

          {step === 'goals' && (
            <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
              <div className="text-center space-y-3">
                <div className="mx-auto w-16 h-16 bg-primary/10 text-primary rounded-full flex items-center justify-center mb-4">
                  <Target className="h-8 w-8" />
                </div>
                <h2 className="text-2xl font-bold">Your Learning Goals</h2>
                <p className="text-muted-foreground">Help us create topics and lessons that actually interest you.</p>
              </div>
              <div className="space-y-5">
                <div className="space-y-3">
                  <Label>Target language</Label>
                  <div className="grid grid-cols-2 gap-3">
                    {SUPPORTED_LANGUAGES.map((lang) => (
                      <Button
                        key={lang.code}
                        variant={formData.target_language === lang.code ? 'default' : 'outline'}
                        className="h-12 text-lg"
                        onClick={() => setFormData({...formData, target_language: lang.code})}
                      >
                        {lang.name}
                      </Button>
                    ))}
                    {UPCOMING_LANGUAGES.map((name) => (
                      <Button key={name} variant="outline" disabled className="h-12 text-lg">
                        {name}
                        <span className="ml-2 text-xs text-muted-foreground">Coming soon</span>
                      </Button>
                    ))}
                  </div>
                </div>
                <div className="space-y-3">
                  <Label>Why are you learning {SUPPORTED_LANGUAGES.find(l => l.code === formData.target_language)?.name ?? 'your target language'}?</Label>
                  <Input 
                    placeholder="e.g. Trip to Mexico, work, partner's family..." 
                    value={formData.goals}
                    onChange={(e) => setFormData({...formData, goals: e.target.value})}
                    className="h-12 rounded-lg"
                  />
                </div>
                <div className="space-y-3">
                  <Label>Interests & Hobbies</Label>
                  <Input 
                    placeholder="e.g. Cooking, Sci-fi, Football, History..." 
                    value={formData.interests}
                    onChange={(e) => setFormData({...formData, interests: e.target.value})}
                    className="h-12 rounded-lg"
                  />
                </div>
              </div>
              <Button className="w-full h-12 rounded-xl text-lg" onClick={completeOnboarding}>
                Complete Setup <ChevronRight className="ml-2 h-5 w-5" />
              </Button>
            </div>
          )}

          {step === 'complete' && (
            <div className="text-center space-y-8 animate-in zoom-in-95 duration-500">
              <div className="mx-auto w-24 h-24 bg-brand-green/25 text-success rounded-full flex items-center justify-center mb-4">
                <CheckCircle className="h-12 w-12" />
              </div>
              <div className="space-y-2">
                <h2 className="text-3xl font-bold">You&apos;re all set!</h2>
                <p className="text-muted-foreground">Your personalized tutor is ready and waiting.</p>
              </div>
              <Button className="w-full h-12 rounded-xl text-lg" onClick={() => router.push('/')}>
                Start Learning Now <ChevronRight className="ml-2 h-5 w-5" />
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
