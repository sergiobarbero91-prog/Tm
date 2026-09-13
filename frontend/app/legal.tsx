import React from 'react';
import { View, Text, ScrollView, StyleSheet, TouchableOpacity, SafeAreaView } from 'react-native';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';

export default function LegalPage() {
  const router = useRouter();

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backButton}>
          <Ionicons name="arrow-back" size={24} color="#FFFFFF" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Información Legal</Text>
      </View>

      <ScrollView style={styles.content} showsVerticalScrollIndicator={false}>
        {/* Política de Privacidad */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>🔒 Política de Privacidad</Text>
          <Text style={styles.lastUpdated}>Última actualización: Enero 2026</Text>
          
          <Text style={styles.paragraph}>
            TaxiMeter Madrid ("la App") respeta tu privacidad y se compromete a proteger tus datos personales.
          </Text>

          <Text style={styles.subTitle}>Datos que Recopilamos</Text>
          <Text style={styles.bulletPoint}>• <Text style={styles.bold}>Cuenta:</Text> Nombre de usuario, nombre completo, número de licencia</Text>
          <Text style={styles.bulletPoint}>• <Text style={styles.bold}>Ubicación:</Text> Solo cuando usas funciones de check-in o navegación GPS</Text>
          <Text style={styles.bulletPoint}>• <Text style={styles.bold}>Actividad:</Text> Check-ins en estaciones/terminales, alertas reportadas</Text>

          <Text style={styles.subTitle}>Cómo Usamos tus Datos</Text>
          <Text style={styles.bulletPoint}>• Mostrar información de estaciones y terminales cercanas</Text>
          <Text style={styles.bulletPoint}>• Permitir el sistema de check-in en ubicaciones</Text>
          <Text style={styles.bulletPoint}>• Facilitar el chat y la radio entre taxistas</Text>
          <Text style={styles.bulletPoint}>• Mejorar la experiencia de la aplicación</Text>

          <Text style={styles.subTitle}>Compartición de Datos</Text>
          <Text style={styles.paragraph}>
            No vendemos ni compartimos tus datos personales con terceros. Tu información solo es visible para:
          </Text>
          <Text style={styles.bulletPoint}>• Otros taxistas (solo nombre de usuario en chat/alertas)</Text>
          <Text style={styles.bulletPoint}>• Administradores de la plataforma (para moderación)</Text>

          <Text style={styles.subTitle}>Seguridad</Text>
          <Text style={styles.paragraph}>
            Utilizamos encriptación y medidas de seguridad estándar de la industria para proteger tus datos.
          </Text>

          <Text style={styles.subTitle}>Tus Derechos</Text>
          <Text style={styles.bulletPoint}>• Acceder a tus datos personales</Text>
          <Text style={styles.bulletPoint}>• Solicitar la eliminación de tu cuenta</Text>
          <Text style={styles.bulletPoint}>• Modificar tu información de perfil</Text>
        </View>

        {/* Términos de Uso */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>📋 Términos de Uso</Text>
          
          <Text style={styles.subTitle}>Uso Aceptable</Text>
          <Text style={styles.paragraph}>
            Al usar TaxiMeter Madrid, aceptas:
          </Text>
          <Text style={styles.bulletPoint}>• Proporcionar información veraz y actualizada</Text>
          <Text style={styles.bulletPoint}>• No usar la app para actividades ilegales</Text>
          <Text style={styles.bulletPoint}>• Respetar a otros usuarios en chat y radio</Text>
          <Text style={styles.bulletPoint}>• No crear alertas falsas intencionalmente</Text>

          <Text style={styles.subTitle}>Sistema de Sanciones</Text>
          <Text style={styles.paragraph}>
            El uso indebido de la plataforma puede resultar en:
          </Text>
          <Text style={styles.bulletPoint}>• Suspensión temporal (6-48 horas)</Text>
          <Text style={styles.bulletPoint}>• Bloqueo permanente en casos graves</Text>
          <Text style={styles.bulletPoint}>• Restricción de funciones específicas</Text>

          <Text style={styles.subTitle}>Limitación de Responsabilidad</Text>
          <Text style={styles.paragraph}>
            TaxiMeter Madrid proporciona información basada en datos de ADIF y AENA. 
            No garantizamos la exactitud absoluta de los horarios mostrados. 
            La app es una herramienta de apoyo, no un sistema oficial de información.
          </Text>

          <Text style={styles.subTitle}>Modificaciones</Text>
          <Text style={styles.paragraph}>
            Nos reservamos el derecho de modificar estos términos. 
            Te notificaremos de cambios significativos a través de la app.
          </Text>
        </View>

        {/* Contacto */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>📧 Contacto</Text>
          <Text style={styles.paragraph}>
            Para cualquier consulta sobre privacidad, términos de uso o problemas técnicos, 
            utiliza nuestro centro de ayuda.
          </Text>
          <TouchableOpacity 
            style={styles.supportButton}
            onPress={() => router.push('/?openSupport=true')}
          >
            <Ionicons name="headset" size={20} color="#FFFFFF" />
            <Text style={styles.supportButtonText}>Centro de Ayuda</Text>
          </TouchableOpacity>
        </View>

        <View style={styles.footer}>
          <Text style={styles.footerText}>
            © 2026 TaxiMeter Madrid. Todos los derechos reservados.
          </Text>
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
  section: {
    backgroundColor: '#1F2937',
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
  },
  sectionTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: '#FFFFFF',
    marginBottom: 8,
  },
  lastUpdated: {
    fontSize: 12,
    color: '#9CA3AF',
    marginBottom: 16,
  },
  subTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#60A5FA',
    marginTop: 16,
    marginBottom: 8,
  },
  paragraph: {
    fontSize: 14,
    color: '#D1D5DB',
    lineHeight: 22,
    marginBottom: 8,
  },
  bulletPoint: {
    fontSize: 14,
    color: '#D1D5DB',
    lineHeight: 24,
    paddingLeft: 8,
  },
  bold: {
    fontWeight: '600',
    color: '#FFFFFF',
  },
  supportButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#6366F1',
    paddingVertical: 12,
    paddingHorizontal: 24,
    borderRadius: 10,
    marginTop: 16,
    gap: 8,
  },
  supportButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
  },
  footer: {
    padding: 24,
    alignItems: 'center',
  },
  footerText: {
    fontSize: 12,
    color: '#6B7280',
  },
});
