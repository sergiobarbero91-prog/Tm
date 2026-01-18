import React from 'react';
import { View, Text, ScrollView, StyleSheet, TouchableOpacity, SafeAreaView } from 'react-native';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';

export default function HelpPage() {
  const router = useRouter();

  const Section = ({ icon, title, children }: { icon: string; title: string; children: React.ReactNode }) => (
    <View style={styles.section}>
      <View style={styles.sectionHeader}>
        <Ionicons name={icon as any} size={24} color="#60A5FA" />
        <Text style={styles.sectionTitle}>{title}</Text>
      </View>
      {children}
    </View>
  );

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backButton}>
          <Ionicons name="arrow-back" size={24} color="#FFFFFF" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Manual de Usuario</Text>
      </View>

      <ScrollView style={styles.content} showsVerticalScrollIndicator={false}>
        {/* Introducción */}
        <View style={styles.intro}>
          <Text style={styles.introTitle}>🚕 Bienvenido a TaxiMeter Madrid</Text>
          <Text style={styles.introText}>
            Tu herramienta para monitorear llegadas a estaciones de tren y terminales de aeropuerto en tiempo real.
          </Text>
        </View>

        {/* Pestañas principales */}
        <Section icon="apps" title="Pestañas Principales">
          <View style={styles.featureItem}>
            <Text style={styles.featureTitle}>🚄 Trenes</Text>
            <Text style={styles.featureDesc}>
              Muestra llegadas a Atocha y Chamartín. Incluye hora de llegada, tipo de tren (AVE, ALVIA, etc.), 
              y andén cuando está disponible.
            </Text>
          </View>
          <View style={styles.featureItem}>
            <Text style={styles.featureTitle}>✈️ Aviones</Text>
            <Text style={styles.featureDesc}>
              Llegadas a todas las terminales del aeropuerto (T1-T4S). 
              Muestra vuelo, origen, aerolínea y estado.
            </Text>
          </View>
          <View style={styles.featureItem}>
            <Text style={styles.featureTitle}>🛣️ Calle</Text>
            <Text style={styles.featureDesc}>
              Vista resumen con la "calle más caliente" (donde hay más actividad), 
              estación y terminal con más llegadas próximas.
            </Text>
          </View>
          <View style={styles.featureItem}>
            <Text style={styles.featureTitle}>📅 Eventos</Text>
            <Text style={styles.featureDesc}>
              Próximos eventos en Madrid que pueden generar demanda de taxis 
              (conciertos, partidos de fútbol, etc.).
            </Text>
          </View>
        </Section>

        {/* Sistema de Score */}
        <Section icon="analytics" title="Sistema de Puntuación">
          <Text style={styles.paragraph}>
            Cada estación y terminal tiene un <Text style={styles.highlight}>Score</Text> que indica 
            el potencial de trabajo:
          </Text>
          <View style={styles.scoreExamples}>
            <View style={styles.scoreItem}>
              <View style={[styles.scoreBadge, { backgroundColor: '#22C55E' }]}>
                <Text style={styles.scoreText}>8+</Text>
              </View>
              <Text style={styles.scoreLabel}>Excelente - Alta demanda</Text>
            </View>
            <View style={styles.scoreItem}>
              <View style={[styles.scoreBadge, { backgroundColor: '#F59E0B' }]}>
                <Text style={styles.scoreText}>4-7</Text>
              </View>
              <Text style={styles.scoreLabel}>Bueno - Demanda media</Text>
            </View>
            <View style={styles.scoreItem}>
              <View style={[styles.scoreBadge, { backgroundColor: '#EF4444' }]}>
                <Text style={styles.scoreText}>0-3</Text>
              </View>
              <Text style={styles.scoreLabel}>Bajo - Poca actividad</Text>
            </View>
          </View>
          <Text style={styles.paragraph}>
            El score se calcula en base a llegadas previas vs próximas llegadas.
          </Text>
        </Section>

        {/* Alertas */}
        <Section icon="notifications" title="Sistema de Alertas">
          <Text style={styles.paragraph}>
            Puedes crear alertas para informar a otros taxistas sobre la situación en estaciones y terminales:
          </Text>
          <View style={styles.alertTypes}>
            <View style={styles.alertItem}>
              <View style={[styles.alertBadge, { backgroundColor: '#EF4444' }]}>
                <Ionicons name="car" size={16} color="#FFF" />
              </View>
              <View style={styles.alertInfo}>
                <Text style={styles.alertTitle}>Sin Taxis</Text>
                <Text style={styles.alertDesc}>No hay taxis disponibles en la ubicación</Text>
              </View>
            </View>
            <View style={styles.alertItem}>
              <View style={[styles.alertBadge, { backgroundColor: '#F59E0B' }]}>
                <Ionicons name="people" size={16} color="#FFF" />
              </View>
              <View style={styles.alertInfo}>
                <Text style={styles.alertTitle}>Barandilla</Text>
                <Text style={styles.alertDesc}>Hay mucha gente esperando taxi</Text>
              </View>
            </View>
          </View>
          
          <View style={styles.warningBox}>
            <Ionicons name="warning" size={24} color="#EF4444" />
            <View style={styles.warningContent}>
              <Text style={styles.warningTitle}>⚠️ IMPORTANTE</Text>
              <Text style={styles.warningText}>
                Utiliza las alertas SOLO cuando la información sea real y verificada.
              </Text>
              <Text style={styles.warningText}>
                Si creas alertas falsas y son detectadas por otros usuarios o el sistema, 
                puedes ser <Text style={styles.warningBold}>BANEADO temporalmente o permanentemente</Text> de la plataforma.
              </Text>
              <Text style={styles.warningSubtext}>
                Las penalizaciones van desde 6 horas hasta baneo permanente según la reincidencia.
              </Text>
            </View>
          </View>
        </Section>

        {/* Check-in */}
        <Section icon="location" title="Sistema de Check-in">
          <Text style={styles.paragraph}>
            Usa el botón <Text style={styles.highlight}>"ENTRAR EN ESTACIÓN/TERMINAL"</Text> para 
            registrar tu presencia. Esto ayuda a otros taxistas a saber cuántos compañeros hay esperando.
          </Text>
          <View style={styles.tipBox}>
            <Ionicons name="bulb" size={20} color="#F59E0B" />
            <Text style={styles.tipText}>
              Recuerda hacer check-out cuando salgas para mantener la información actualizada.
            </Text>
          </View>
        </Section>

        {/* Juegos */}
        <Section icon="game-controller" title="Juegos Online">
          <Text style={styles.paragraph}>
            Mientras esperas, puedes jugar con otros taxistas:
          </Text>
          <Text style={styles.bulletPoint}>🚢 <Text style={styles.bold}>Hundir la Flota</Text> - Coloca tus barcos y hunde los del rival</Text>
          <Text style={styles.bulletPoint}>⭕ <Text style={styles.bold}>Tres en Raya</Text> - Clásico juego de X y O</Text>
          <Text style={styles.bulletPoint}>🔤 <Text style={styles.bold}>Ahorcado</Text> - Adivina la palabra antes de que se complete el dibujo</Text>
          <Text style={[styles.paragraph, { marginTop: 8 }]}>
            Todas las partidas son "mejor de 3" rondas.
          </Text>
        </Section>

        {/* Chat y Radio */}
        <Section icon="chatbubbles" title="Chat y Radio">
          <Text style={styles.paragraph}>
            Comunícate con otros taxistas:
          </Text>
          <Text style={styles.bulletPoint}>💬 <Text style={styles.bold}>Chat</Text> - Mensajes de texto en canales (general, estaciones)</Text>
          <Text style={styles.bulletPoint}>🎙️ <Text style={styles.bold}>Radio PTT</Text> - Comunicación por voz en tiempo real (pulsa para hablar)</Text>
          <Text style={[styles.paragraph, { marginTop: 12, color: '#F87171' }]}>
            ⚠️ El mal uso del chat puede resultar en bloqueo temporal o permanente.
          </Text>
        </Section>

        {/* Filtros */}
        <Section icon="options" title="Filtros y Opciones">
          <Text style={styles.paragraph}>
            Personaliza la información mostrada:
          </Text>
          <Text style={styles.bulletPoint}>⏱️ <Text style={styles.bold}>Ventana de tiempo</Text> - 30 o 60 minutos</Text>
          <Text style={styles.bulletPoint}>🌙 <Text style={styles.bold}>Turno</Text> - Diurno (6:00-21:00), Nocturno (21:00-6:00), o Todos</Text>
        </Section>

        {/* Soporte */}
        <View style={styles.supportBox}>
          <Ionicons name="chatbubbles" size={32} color="#60A5FA" />
          <Text style={styles.supportTitle}>¿Necesitas ayuda?</Text>
          <Text style={styles.supportText}>
            Abre un ticket de soporte y nuestro equipo te ayudará lo antes posible.
          </Text>
          <TouchableOpacity 
            style={styles.supportButton}
            onPress={() => router.push('/?openSupport=true')}
          >
            <Ionicons name="headset" size={20} color="#FFFFFF" />
            <Text style={styles.supportButtonText}>Centro de Ayuda</Text>
          </TouchableOpacity>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#111827',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    backgroundColor: '#1F2937',
    borderBottomWidth: 1,
    borderBottomColor: '#374151',
  },
  backButton: {
    padding: 8,
    marginRight: 12,
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#FFFFFF',
  },
  content: {
    flex: 1,
    padding: 16,
  },
  intro: {
    backgroundColor: '#1E3A5F',
    borderRadius: 12,
    padding: 20,
    marginBottom: 16,
    alignItems: 'center',
  },
  introTitle: {
    fontSize: 22,
    fontWeight: '700',
    color: '#FFFFFF',
    marginBottom: 8,
  },
  introText: {
    fontSize: 14,
    color: '#93C5FD',
    textAlign: 'center',
    lineHeight: 22,
  },
  section: {
    backgroundColor: '#1F2937',
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 16,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#FFFFFF',
    marginLeft: 12,
  },
  paragraph: {
    fontSize: 14,
    color: '#D1D5DB',
    lineHeight: 22,
  },
  highlight: {
    color: '#60A5FA',
    fontWeight: '600',
  },
  bold: {
    fontWeight: '600',
    color: '#FFFFFF',
  },
  bulletPoint: {
    fontSize: 14,
    color: '#D1D5DB',
    lineHeight: 28,
    paddingLeft: 4,
  },
  featureItem: {
    marginBottom: 16,
    paddingBottom: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#374151',
  },
  featureTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#FFFFFF',
    marginBottom: 4,
  },
  featureDesc: {
    fontSize: 14,
    color: '#9CA3AF',
    lineHeight: 20,
  },
  scoreExamples: {
    marginVertical: 12,
  },
  scoreItem: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 8,
  },
  scoreBadge: {
    width: 40,
    height: 28,
    borderRadius: 6,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  scoreText: {
    color: '#FFFFFF',
    fontWeight: '700',
    fontSize: 14,
  },
  scoreLabel: {
    color: '#D1D5DB',
    fontSize: 14,
  },
  alertTypes: {
    marginTop: 12,
  },
  alertItem: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
  },
  alertBadge: {
    width: 36,
    height: 36,
    borderRadius: 8,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  alertInfo: {
    flex: 1,
  },
  alertTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#FFFFFF',
  },
  alertDesc: {
    fontSize: 12,
    color: '#9CA3AF',
  },
  warningBox: {
    flexDirection: 'row',
    backgroundColor: '#450A0A',
    borderRadius: 10,
    padding: 14,
    marginTop: 16,
    borderWidth: 1,
    borderColor: '#7F1D1D',
  },
  warningContent: {
    flex: 1,
    marginLeft: 12,
  },
  warningTitle: {
    fontSize: 14,
    fontWeight: '700',
    color: '#FCA5A5',
    marginBottom: 8,
  },
  warningText: {
    fontSize: 13,
    color: '#FECACA',
    lineHeight: 20,
    marginBottom: 6,
  },
  warningBold: {
    fontWeight: '700',
    color: '#FCA5A5',
  },
  warningSubtext: {
    fontSize: 11,
    color: '#F87171',
    marginTop: 4,
    fontStyle: 'italic',
  },
  tipBox: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    backgroundColor: '#422006',
    borderRadius: 8,
    padding: 12,
    marginTop: 12,
  },
  tipText: {
    flex: 1,
    marginLeft: 10,
    fontSize: 13,
    color: '#FCD34D',
    lineHeight: 20,
  },
  supportBox: {
    backgroundColor: '#1E3A5F',
    borderRadius: 12,
    padding: 24,
    alignItems: 'center',
    marginBottom: 24,
  },
  supportTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#FFFFFF',
    marginTop: 12,
    marginBottom: 8,
  },
  supportText: {
    fontSize: 14,
    color: '#93C5FD',
    textAlign: 'center',
  },
});
