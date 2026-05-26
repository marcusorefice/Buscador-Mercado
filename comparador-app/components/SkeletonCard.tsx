import React, { useEffect, useRef } from 'react';
import { View, StyleSheet, Animated } from 'react-native';

export const SkeletonCard = () => {
  const fadeAnim = useRef(new Animated.Value(0.3)).current;

  useEffect(() => {
    Animated.loop(
      Animated.sequence([
        Animated.timing(fadeAnim, {
          toValue: 0.7,
          duration: 800,
          useNativeDriver: true,
        }),
        Animated.timing(fadeAnim, {
          toValue: 0.3,
          duration: 800,
          useNativeDriver: true,
        }),
      ])
    ).start();
  }, [fadeAnim]);

  return (
    <Animated.View style={[styles.card, { opacity: fadeAnim }]}>
      <View style={styles.imagePlaceholder} />
      <View style={styles.content}>
        <View style={styles.titlePlaceholder} />
        <View style={styles.titlePlaceholderShort} />
        <View style={styles.brandPlaceholder} />
        <View style={styles.pricePlaceholder} />
        <View style={styles.footerPlaceholder} />
      </View>
    </Animated.View>
  );
};

const styles = StyleSheet.create({
  card: {
    width: '49%',
    marginVertical: 6,
    backgroundColor: '#ffffff',
    borderRadius: 12,
    elevation: 3,
    overflow: 'hidden',
  },
  imagePlaceholder: { width: '100%', aspectRatio: 1, backgroundColor: '#e0e0e0' },
  content: { padding: 10, flex: 1, justifyContent: 'space-between' },
  titlePlaceholder: { height: 14, backgroundColor: '#e0e0e0', borderRadius: 4, marginBottom: 6 },
  titlePlaceholderShort: { height: 14, backgroundColor: '#e0e0e0', borderRadius: 4, width: '70%', marginBottom: 12 },
  brandPlaceholder: { height: 10, backgroundColor: '#e0e0e0', borderRadius: 4, width: '40%', marginBottom: 12 },
  pricePlaceholder: { height: 20, backgroundColor: '#e0e0e0', borderRadius: 4, width: '60%', marginBottom: 16 },
  footerPlaceholder: { height: 32, backgroundColor: '#e0e0e0', borderRadius: 4, width: '100%' },
});