import {
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  Modal,
  Animated,
  ScrollView,
} from "react-native";
import { useState, useRef, useEffect } from "react";
import { colors } from "../assets/colors/colors";
import { Octicons } from "@expo/vector-icons";

interface RoutineCreateProps {
  onConfirm: (data: {
    goal: string;
    body_parts: string[];
    session_time: string;
    injury: string;
  }) => void;
  onClose: () => void;
}

const goals = ["근력", "다이어트", "체력", "근비대"];
const body_parts = ["어깨", "등", "가슴", "하체", "팔", "복근"];
const session_times = ["30분", "60분", "90분", "120분 +"];

export default function RoutineCreate({
  onConfirm,
  onClose,
}: RoutineCreateProps) {
  const [selected_goal, set_selected_goal] = useState<string>("근력");
  const [selected_parts, set_selected_parts] = useState<string[]>(["어깨"]);
  const [selected_time, set_selected_time] = useState<string>("30분");
  const [injury, set_injury] = useState("");

  const slide_anim = useRef(new Animated.Value(600)).current;

  useEffect(() => {
    Animated.timing(slide_anim, {
      toValue: 0,
      duration: 300,
      useNativeDriver: true,
    }).start();
  }, []);

  const handle_close = () => {
    Animated.timing(slide_anim, {
      toValue: 600,
      duration: 300,
      useNativeDriver: true,
    }).start(() => onClose());
  };

  const toggle_part = (part: string) => {
    set_selected_parts((prev) =>
      prev.includes(part) ? prev.filter((p) => p !== part) : [...prev, part],
    );
  };

  const handle_confirm = () => {
    onConfirm({
      goal: selected_goal,
      body_parts: selected_parts,
      session_time: selected_time,
      injury,
    });
  };

  return (
    <Modal
      transparent
      animationType="fade"
      visible
      onRequestClose={handle_close}
    >
      <View style={styles.overlay}>
        {/* 딤 배경 */}
        <TouchableOpacity
          style={styles.dim}
          activeOpacity={1}
          onPress={handle_close}
        />

        {/* 바텀시트 */}
        <Animated.View
          style={[styles.sheet, { transform: [{ translateY: slide_anim }] }]}
        >
          {/* 헤더 */}
          <View style={styles.sheet_header}>
            <View style={styles.placeholder} />
            <Text style={styles.sheet_title}>루틴 생성</Text>
            <TouchableOpacity
              style={styles.close_button}
              onPress={handle_close}
            >
              <Octicons name="x" size={24} color={colors.primary} />
            </TouchableOpacity>
          </View>

          {/* 내용 */}
          <View style={styles.content}>
            {/* 목표 선택 */}
            <View style={styles.section}>
              <Text style={styles.section_title}>목표 선택</Text>
              <View style={styles.chip_row}>
                {goals.map((goal) => (
                  <TouchableOpacity
                    key={goal}
                    style={[
                      styles.chip,
                      selected_goal === goal && styles.chip_active,
                    ]}
                    onPress={() => set_selected_goal(goal)}
                    activeOpacity={0.8}
                  >
                    <Text
                      style={[
                        styles.chip_text,
                        selected_goal === goal && styles.chip_text_active,
                      ]}
                    >
                      {goal}
                    </Text>
                  </TouchableOpacity>
                ))}
              </View>
            </View>

            {/* 부위 선택 */}
            <View style={styles.section}>
              <Text style={styles.section_title}>부위 선택</Text>
              <ScrollView horizontal showsHorizontalScrollIndicator={false}>
                <View style={styles.chip_row}>
                  {body_parts.map((part) => (
                    <TouchableOpacity
                      key={part}
                      style={[
                        styles.chip,
                        selected_parts.includes(part) && styles.chip_active,
                      ]}
                      onPress={() => toggle_part(part)}
                      activeOpacity={0.8}
                    >
                      <Text
                        style={[
                          styles.chip_text,
                          selected_parts.includes(part) &&
                            styles.chip_text_active,
                        ]}
                      >
                        {part}
                      </Text>
                    </TouchableOpacity>
                  ))}
                </View>
              </ScrollView>
            </View>

            {/* 세션 시간 */}
            <View style={styles.section}>
              <Text style={styles.section_title}>세션 시간</Text>
              <View style={styles.chip_row}>
                {session_times.map((time) => (
                  <TouchableOpacity
                    key={time}
                    style={[
                      styles.chip,
                      selected_time === time && styles.chip_active,
                    ]}
                    onPress={() => set_selected_time(time)}
                    activeOpacity={0.8}
                  >
                    <Text
                      style={[
                        styles.chip_text,
                        selected_time === time && styles.chip_text_active,
                      ]}
                    >
                      {time}
                    </Text>
                  </TouchableOpacity>
                ))}
              </View>
            </View>

            {/* 부상 부위 (선택) */}
            <View style={styles.section}>
              <Text style={styles.section_title}>부상 부위 (선택)</Text>
              <TextInput
                style={styles.input}
                placeholder="부상 부위 입력"
                placeholderTextColor={colors.border}
                value={injury}
                onChangeText={set_injury}
              />
            </View>
          </View>

          {/* 확인 버튼 */}
          <TouchableOpacity
            style={styles.confirm_button}
            onPress={handle_confirm}
            activeOpacity={0.8}
          >
            <Text style={styles.confirm_button_text}>확인</Text>
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
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    paddingHorizontal: 20,
    paddingBottom: 40,
    paddingTop: 20,
  },
  sheet_header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 32,
  },
  placeholder: {
    width: 24,
  },
  close_button: {
    width: 24,
    alignItems: "center",
  },
  sheet_title: {
    fontFamily: "semibold",
    fontSize: 18,
    color: colors.primary,
    textAlign: "center",
    flex: 1,
  },
  content: {
    gap: 32,
    marginBottom: 32,
  },
  section: {
    gap: 8,
  },
  section_title: {
    fontFamily: "semibold",
    fontSize: 16,
    color: colors.primary,
  },
  chip_row: {
    flexDirection: "row",
    gap: 8,
  },
  chip: {
    backgroundColor: colors.select,
    borderRadius: 8,
    height: 29,
    paddingHorizontal: 12,
    alignItems: "center",
    justifyContent: "center",
  },
  chip_active: {
    backgroundColor: colors.primary,
  },
  chip_text: {
    fontFamily: "regular",
    fontSize: 14,
    color: colors.primary,
  },
  chip_text_active: {
    color: colors.white,
  },
  input: {
    fontFamily: "regular",
    fontSize: 16,
    color: colors.primary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    height: 45,
    paddingHorizontal: 10,
  },
  confirm_button: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
    justifyContent: "center",
  },
  confirm_button_text: {
    fontFamily: "medium",
    fontSize: 16,
    color: colors.white,
  },
});
