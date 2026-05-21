import {
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
  Modal,
  Animated,
} from "react-native";
import { Picker } from "@react-native-picker/picker";
import { useState, useRef, useEffect } from "react";
import { colors } from "../assets/colors/colors";
import { Octicons } from "@expo/vector-icons";

interface BirthDateBottomSheetProps {
  onConfirm: (date: string) => void;
  onClose: () => void;
}

export default function BirthDateBottomSheet({
  onConfirm,
  onClose,
}: BirthDateBottomSheetProps) {
  const current_year = new Date().getFullYear();

  const years = Array.from({ length: 100 }, (_, i) => current_year - i);
  const months = Array.from({ length: 12 }, (_, i) => i + 1);
  const days = Array.from({ length: 31 }, (_, i) => i + 1);

  const [selected_year, set_selected_year] = useState(current_year);
  const [selected_month, set_selected_month] = useState(1);
  const [selected_day, set_selected_day] = useState(1);

  const slide_anim = useRef(new Animated.Value(500)).current;

  useEffect(() => {
    // 열릴 때 아래→위 슬라이드
    Animated.timing(slide_anim, {
      toValue: 0,
      duration: 300,
      useNativeDriver: true,
    }).start();
  }, []);

  const handle_confirm = () => {
    const date = `${selected_year}년 ${selected_month}월 ${selected_day}일`;
    onConfirm(date);
  };

  return (
    <Modal transparent animationType="fade" visible onRequestClose={onClose}>
      <View style={styles.overlay}>
        {/* 딤 배경 */}
        <TouchableOpacity
          style={styles.dim}
          activeOpacity={1}
          onPress={onClose}
        />

        {/* 바텀시트 */}
        <Animated.View
          style={[styles.sheet, { transform: [{ translateY: slide_anim }] }]}
        >
          <View style={styles.sheetHeader}>
            <View style={styles.placeholder} />
            <Text style={styles.sheetTitle}>생년월일 선택</Text>
            <TouchableOpacity style={styles.closeButton} onPress={onClose}>
              <Octicons name="x" size={32} color={colors.primary} />
            </TouchableOpacity>
          </View>

          {/* Picker */}
          <View style={styles.pickerContainer}>
            <Picker
              style={styles.picker}
              selectedValue={selected_year}
              onValueChange={(v) => set_selected_year(Number(v))}
              itemStyle={styles.pickerItem}
            >
              {years.map((year) => (
                <Picker.Item
                  key={year}
                  label={`${year}년`}
                  value={year}
                  color={
                    selected_year === year ? colors.primary : colors.button
                  }
                />
              ))}
            </Picker>

            <Picker
              style={styles.picker}
              selectedValue={selected_month}
              onValueChange={(v) => set_selected_month(Number(v))}
              itemStyle={styles.pickerItem}
            >
              {months.map((month) => (
                <Picker.Item
                  key={month}
                  label={`${month}월`}
                  value={month}
                  color={
                    selected_month === month ? colors.primary : colors.button
                  }
                />
              ))}
            </Picker>

            <Picker
              style={styles.picker}
              selectedValue={selected_day}
              onValueChange={(v) => set_selected_day(Number(v))}
              itemStyle={styles.pickerItem}
            >
              {days.map((day) => (
                <Picker.Item
                  key={day}
                  label={`${day}일`}
                  value={day}
                  color={selected_day === day ? colors.primary : colors.button}
                />
              ))}
            </Picker>
          </View>

          {/* 확인 버튼 */}
          <TouchableOpacity
            style={styles.confirmButton}
            onPress={handle_confirm}
            activeOpacity={0.8}
          >
            <Text style={styles.confirmButtonText}>확인</Text>
          </TouchableOpacity>
        </Animated.View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    justifyContent: "flex-end",
    backgroundColor: "rgba(0,0,0,0.2)",
  },
  dim: {
    flex: 1,
  },
  sheet: {
    backgroundColor: colors.white,
    borderTopLeftRadius: 30,
    borderTopRightRadius: 30,
    paddingHorizontal: 20,
    paddingBottom: 40,
    paddingTop: 20,
    height: 410,
  },
  sheetHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 8,
  },
  placeholder: {
    width: 32,
  },
  closeButton: {
    width: 32,
    alignItems: "center",
  },
  sheetTitle: {
    fontFamily: "semibold",
    fontSize: 18,
    color: colors.primary,
    textAlign: "center",
    flex: 1,
  },
  pickerContainer: {
    flexDirection: "row",
    flex: 1,
  },
  picker: {
    flex: 1,
  },
  pickerItem: {
    fontFamily: "regular",
    fontSize: 16,
    color: colors.primary,
  },
  confirmButton: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
    marginTop: 8,
  },
  confirmButtonText: {
    fontFamily: "medium",
    fontSize: 16,
    color: colors.white,
  },
});
